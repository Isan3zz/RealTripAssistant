"""Update INTAKE_PROMPT output format to include origin."""
with open('travel_planning_agent/prompts.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = """### 信息完整时
{
  "complete": true,
  "constraints": {
    "destination": "成都",
    "start_date": "2026-05-04",
    "days": 3,
    "travelers": "2位成人",
    "budget": 5000,
    "pace": "moderate",
    "interests": []
  }
}

### 信息不完整时
{
  "complete": false,
  "question": "请问您的预算是多少？",
  "extracted": {
    "destination": "成都",
    "start_date": "2026-05-04",
    "days": 3,
    "travelers": "2位成人",
    "budget": null,
    "pace": null,
    "interests": null
  }
}

## 规则

- 用户说了什么就提取什么，没说的字段填 null
- extracted 里的已有信息不要丢弃，累加
- 用户可能在已有计划基础上修改，比如"改成两个人"→ travelers 从 1 改 2，其他不变
- 一次只问一个问题，追问顺序：日期 → 天数 → 预算
- 基于已提取的信息追问，已经知道了就别再问"""

new = """### 信息完整时
{
  "complete": true,
  "constraints": {
    "destination": "西安",
    "start_date": "2026-05-08",
    "days": 3,
    "origin": "成都",
    "travelers": "2位成人",
    "budget": 5000,
    "pace": "moderate",
    "interests": ["历史", "美食"]
  }
}

### 信息不完整时
{
  "complete": false,
  "question": "请问您从哪个城市出发？",
  "extracted": {
    "destination": "西安",
    "start_date": null,
    "days": null,
    "origin": null,
    "travelers": null,
    "budget": null,
    "pace": null,
    "interests": null
  }
}

## 规则

- 用户说了什么就提取什么，没说的字段填 null
- extracted 里的已有信息不要丢弃，累加
- 用户可能在已有计划基础上修改，比如"改成两个人"→ travelers 从 1 改 2，其他不变
- 一次只问一个问题，追问顺序：出发城市 → 日期 → 天数 → 预算
- 基于已提取的信息追问，已经知道了就别再问
- 如果用户没说出发城市且目的地已知，提示"请问您从哪个城市出发？""""

if old in content:
    content = content.replace(old, new)
    with open('travel_planning_agent/prompts.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('Not found')
