# DEVLAND — GitHub Ready

Финальная frontend-версия сервиса для маркетплейса девелоперских активов.

## Что внутри
- Vite + React + React Router
- role-based auth
- marketplace и карточки лотов
- shortlist и compare workspace
- investor dashboard
- seller CRM table и listing form
- data room и NDA / access requests
- вопросы и ответы продавца
- deals pipeline kanban
- CRUD по пользователям и компаниям
- admin overview и audit log
- localStorage persistence
- готовые конфиги для Vercel и Netlify

## Демо-аккаунты
- investor@devland.ru / 123456
- seller@devland.ru / 123456
- admin@devland.ru / 123456

## Запуск локально
```bash
npm install
npm run dev
```

## Production build
```bash
npm install
npm run build
npm run preview
```

## Загрузка в GitHub
```bash
git init
git add .
git commit -m "Initial DEVLAND"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/devland.git
git push -u origin main
```

## Деплой на Vercel
Проект уже содержит `vercel.json` для корректной работы SPA-роутинга.

## Деплой на Netlify
Проект уже содержит `netlify.toml` с redirect на `index.html`.
