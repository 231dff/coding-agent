---
name: typescript_config
description: TypeScript 项目配置与类型检查
trigger: 当任务涉及 tsconfig、类型错误或 TS 项目构建时
category: original
tools: execute, sandbox_read
---

## tsconfig.json 关键字段

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "./dist",
    "rootDir": "./src"
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}