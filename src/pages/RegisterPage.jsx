import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Button, Card, FieldGrid, Input, Select } from '../components/ui';

export function RegisterPage() {
  const { register } = useApp();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'investor', companyName: '', city: 'Москва', phone: '' });
  const [error, setError] = useState('');

  function patch(key, value) { setForm((prev) => ({ ...prev, [key]: value })); }

  function submit(e) {
    e.preventDefault();
    const result = register(form);
    if (!result.ok) return setError(result.message);
    navigate('/marketplace');
  }

  return (
    <div className="auth-shell auth-shell-light">
      <Card className="auth-card wide">
        <form onSubmit={submit} className="stack-lg">
          <div>
            <h2>Регистрация</h2>
            <p className="muted">Создайте профиль и компанию, чтобы сразу тестировать сервис.</p>
          </div>
          <FieldGrid>
            <Input label="Имя" value={form.name} onChange={(e) => patch('name', e.target.value)} />
            <Input label="Email" value={form.email} onChange={(e) => patch('email', e.target.value)} />
            <Input label="Пароль" type="password" value={form.password} onChange={(e) => patch('password', e.target.value)} />
            <Select label="Роль" value={form.role} onChange={(e) => patch('role', e.target.value)} options={['investor', 'developer', 'seller', 'broker']} />
            <Input label="Компания" value={form.companyName} onChange={(e) => patch('companyName', e.target.value)} />
            <Input label="Город" value={form.city} onChange={(e) => patch('city', e.target.value)} />
            <Input label="Телефон" value={form.phone} onChange={(e) => patch('phone', e.target.value)} />
          </FieldGrid>
          {error && <div className="alert alert-error">{error}</div>}
          <div className="actions-row">
            <Button type="submit">Создать аккаунт</Button>
            <Link className="btn btn-secondary" to="/login">Назад ко входу</Link>
          </div>
        </form>
      </Card>
    </div>
  );
}
