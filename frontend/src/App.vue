<template>
  <router-view />
</template>

<style>
:root {
  color: #123e45;
  background: #f3fbf9;
  --rt-bg: #f3fbf9;
  --rt-bg-strong: #dff5f1;
  --rt-panel: rgba(255, 255, 255, 0.92);
  --rt-panel-solid: #ffffff;
  --rt-panel-soft: #eef9f7;
  --rt-panel-muted: #dff1f2;
  --rt-border: rgba(31, 90, 101, 0.2);
  --rt-border-strong: rgba(31, 90, 101, 0.34);
  --rt-text: #123e45;
  --rt-muted: #345963;
  --rt-primary: #2a9d8f;
  --rt-primary-soft: #e4f8f5;
  --rt-primary-ink: #123e45;
  --rt-accent: #ffbe5c;
  --rt-accent-soft: #fff4d9;
  --rt-coral: #ff8c6b;
  --rt-sky: #dff7fb;
  --rt-success: #168773;
  --rt-warning: #b87518;
  --rt-shadow: 0 24px 80px rgba(56, 120, 137, 0.16);
  --rt-shadow-soft: 0 14px 36px rgba(56, 120, 137, 0.1);
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  font-family: Aptos, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background:
    radial-gradient(circle at 12% 10%, rgba(42, 157, 143, 0.18), transparent 26%),
    radial-gradient(circle at 82% 8%, rgba(255, 190, 92, 0.22), transparent 24%),
    linear-gradient(180deg, #fbfffd 0%, var(--rt-bg) 48%, #e5f6f4 100%);
  color: var(--rt-text);
  text-rendering: optimizeLegibility;
}

button,
input,
textarea {
  font-family: inherit;
}

::selection {
  background: rgba(42, 157, 143, 0.22);
}

.el-card {
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: var(--rt-panel);
  box-shadow: var(--rt-shadow-soft);
  backdrop-filter: blur(18px);
}

.el-card__header {
  padding: 15px 18px;
  border-bottom: 1px solid var(--rt-border);
  font-weight: 700;
  color: var(--rt-text);
}

.el-card__body {
  padding: 18px;
}

.el-button {
  border-radius: 7px;
  font-weight: 700;
  letter-spacing: 0;
}

.el-button--primary {
  background: linear-gradient(135deg, var(--rt-primary) 0%, #55c6b8 100%);
  border-color: rgba(42, 157, 143, 0.14);
  box-shadow: 0 12px 26px rgba(42, 157, 143, 0.24);
}

.el-button--primary:hover,
.el-button--primary:focus {
  background: linear-gradient(135deg, #248f82 0%, #45b9ad 100%);
  border-color: rgba(42, 157, 143, 0.22);
}

.el-tag {
  border-radius: 999px;
  font-weight: 700;
}

.el-tag--success.el-tag--plain {
  --el-tag-bg-color: rgba(42, 157, 143, 0.1);
  --el-tag-border-color: rgba(42, 157, 143, 0.24);
  --el-tag-text-color: var(--rt-success);
}

.el-textarea__inner,
.el-input__wrapper {
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  color: var(--rt-text);
  box-shadow: 0 0 0 1px var(--rt-border) inset;
}

.el-textarea__inner::placeholder,
.el-input__inner::placeholder {
  color: #4d7079;
  opacity: 1;
}

.el-textarea__inner:focus,
.el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1px rgba(42, 157, 143, 0.55) inset, 0 0 0 4px rgba(42, 157, 143, 0.12);
}

.el-table {
  border-radius: 8px;
  overflow: hidden;
}

.el-dialog {
  border: 1px solid var(--rt-border);
  border-radius: 8px;
  background: var(--rt-panel-solid);
  box-shadow: var(--rt-shadow);
}

@media (max-width: 720px) {
  .el-card__body {
    padding: 14px;
  }
}
</style>
