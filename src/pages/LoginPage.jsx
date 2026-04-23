import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Button, Card, Input } from '../components/ui';

export function LoginPage() {
  const { login } = useApp();
  const navigate = useNavigate();
  const [email, setEmail] = useState('investor@devland.ru');
  const [password, setPassword] = useState('123456');
  const [error, setError] = useState('');

  function submit(e) {
    e.preventDefault();
    const result = login(email, password);
    if (!result.ok) return setError(result.message);
    if (['seller', 'broker', 'admin'].includes(result.user.role)) navigate('/crm/listings');
    else navigate('/marketplace');
  }

  return (
    <div className="auth-shell">
      <div className="auth-copy">
        <div className="hero-badge">Full Codex-ready service</div>
        <h1>DEVLAND — production-like платформа девелоперских активов</h1>
        <p>Маркетплейс, CRM, data room, pipeline, compare workspace и административные CRUD-разделы в одном приложении.</p>
        <ul className="feature-list">
          <li>Маркетплейс и карточки лотов</li>
          <li>CRM-таблица лотов и pipeline сделок</li>
          <li>CRUD по пользователям и компаниям</li>
          <li>Вопросы, NDA и data room</li>
        </ul>
      </div>
      <Card className="auth-card">
        <form onSubmit={submit} className="stack-lg">
          <div>
            <h2>Вход</h2>
            <p className="muted">Используйте демо-аккаунт или создайте новый профиль.</p>
          </div>
          <Input label="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input label="Пароль" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error && <div className="alert alert-error">{error}</div>}
          <Button type="submit">Войти</Button>
          <Link className="btn btn-secondary" to="/register">Создать аккаунт</Link>
          <div className="hint">Demos: investor@devland.ru / seller@devland.ru / admin@devland.ru — пароль 123456</div>
        </form>
      </Card>
    </div>
  );
}
