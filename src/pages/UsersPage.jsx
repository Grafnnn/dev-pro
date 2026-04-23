import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Button, Card, EmptyState, FieldGrid, Input, PageHeader, Select } from '../components/ui';

const blank = { id: '', name: '', email: '', password: '123456', role: 'investor', companyId: '', city: '', phone: '', isActive: true };

export function UsersPage() {
  const { db, upsertUser, deleteUser } = useApp();
  const [draft, setDraft] = useState(blank);
  function patch(key, value) { setDraft((prev) => ({ ...prev, [key]: value })); }
  function edit(user) { setDraft(user); }
  function save() { upsertUser(draft); setDraft(blank); }

  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Admin CRUD" title="Пользователи" subtitle="Управление ролями, компаниями и доступом." />
      <div className="two-col-grid">
        <Card>
          <div className="stack-md">
            <h3>{draft.id ? 'Редактировать пользователя' : 'Новый пользователь'}</h3>
            <FieldGrid>
              <Input label="Имя" value={draft.name} onChange={(e) => patch('name', e.target.value)} />
              <Input label="Email" value={draft.email} onChange={(e) => patch('email', e.target.value)} />
              <Input label="Пароль" value={draft.password} onChange={(e) => patch('password', e.target.value)} />
              <Select label="Роль" value={draft.role} onChange={(e) => patch('role', e.target.value)} options={['investor', 'developer', 'seller', 'broker', 'admin']} />
              <Select label="Компания" value={draft.companyId} onChange={(e) => patch('companyId', e.target.value)} options={db.companies.map((c) => ({ value: c.id, label: c.name }))} />
              <Input label="Город" value={draft.city} onChange={(e) => patch('city', e.target.value)} />
              <Input label="Телефон" value={draft.phone} onChange={(e) => patch('phone', e.target.value)} />
            </FieldGrid>
            <label className="checkbox-row"><input type="checkbox" checked={draft.isActive} onChange={(e) => patch('isActive', e.target.checked)} /> Active</label>
            <div className="actions-row"><Button onClick={save}>Сохранить</Button><Button variant="secondary" onClick={() => setDraft(blank)}>Сбросить</Button></div>
          </div>
        </Card>
        <Card>
          <div className="stack-md">
            <h3>Список пользователей</h3>
            {db.users.length === 0 ? <EmptyState title="Пользователей нет" /> : db.users.map((user) => (
              <div key={user.id} className="table-row cardish">
                <div><strong>{user.name}</strong><div className="muted small">{user.email} · {user.role}</div></div>
                <div className="actions-row wrap"><Button variant="secondary" className="mini" onClick={() => edit(user)}>Редактировать</Button><Button variant="danger" className="mini" onClick={() => deleteUser(user.id)}>Удалить</Button></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
