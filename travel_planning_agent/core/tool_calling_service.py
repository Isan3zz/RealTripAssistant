import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from travel_planning_agent.tools import execute_tool

logger = logging.getLogger(__name__)


class ToolCallingService:
    def run(
        self,
        *,
        client,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        extract_json,
        summarize_tool_input,
        compute_max_tokens,
        max_rounds: int = 25,
    ) -> dict:
        total_tokens = 0
        tool_calls_log: list[dict] = []
        json_retry_count = 0
        current_max_tokens = compute_max_tokens(messages)

        for _ in range(max_rounds):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools if tools else None,
                max_tokens=current_max_tokens,
            )

            choice = response.choices[0]
            message = choice.message

            if response.usage:
                total_tokens += (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

            tool_calls = message.tool_calls
            if not tool_calls:
                full_text = message.content or ""
                parsed = extract_json(full_text)
                if parsed:
                    return {
                        "success": True,
                        "data": parsed,
                        "text": full_text,
                        "tokens_used": total_tokens,
                        "tool_calls_log": tool_calls_log,
                    }

                if json_retry_count < 2:
                    json_retry_count += 1
                    is_truncated = full_text.strip().startswith("{") and not full_text.strip().endswith("}")
                    if is_truncated:
                        current_max_tokens = min(current_max_tokens * 2, 16384)
                        logger.warning("输出被截断（max_tokens=%d），加倍重试", current_max_tokens)
                        messages.append({"role": "assistant", "content": full_text})
                        messages.append({
                            "role": "user",
                            "content": "输出被截断了，请继续输出完整内容。只输出纯 JSON，不要额外文本。",
                        })
                    else:
                        logger.warning("JSON 解析失败（第 %d 次），重新请求纯 JSON", json_retry_count)
                        messages.append({
                            "role": "user",
                            "content": "请只输出纯 JSON（不要 markdown 包裹），确保格式正确可解析。",
                        })
                    continue

                return {
                    "success": True,
                    "data": None,
                    "text": full_text,
                    "tokens_used": total_tokens,
                    "tool_calls_log": tool_calls_log,
                }

            assistant_msg: dict = {"role": "assistant", "content": message.content or "", "tool_calls": []}
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning

            tc_list = []
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    tool_input = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_input = {}
                logger.info("LLM 调用工具: %s, 参数: %s", tool_name, tool_input)
                assistant_msg["tool_calls"].append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tc.function.arguments},
                })
                tc_list.append((tc.id, tool_name, tool_input))

            results = {}
            with ThreadPoolExecutor(max_workers=min(len(tc_list), 5)) as executor:
                future_map = {
                    executor.submit(execute_tool, tool_name, tool_input): (tc_id, tool_name, tool_input)
                    for tc_id, tool_name, tool_input in tc_list
                }
                for future in as_completed(future_map):
                    tc_id, tool_name, tool_input = future_map[future]
                    try:
                        results[tc_id] = future.result()
                    except Exception as exc:
                        results[tc_id] = f"{tool_name}: 执行异常 - {exc}"

            messages.append(assistant_msg)
            for tc_id, tool_name, tool_input in tc_list:
                tool_result = results.get(tc_id, "查询失败")
                tool_calls_log.append(
                    {
                        "tool": tool_name,
                        "input": summarize_tool_input(tool_name, tool_input),
                        "result": tool_result[:500] if tool_result else "",
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": tool_result,
                    }
                )

        return {
            "success": False,
            "error": "工具调用超过最大轮数（25 轮）",
            "tokens_used": total_tokens,
            "tool_calls_log": tool_calls_log,
        }
