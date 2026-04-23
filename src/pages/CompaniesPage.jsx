import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Button, Card, EmptyState, FieldGrid, Input, PageHeader, Textarea } from '../components/ui';

const blank = { id: '', name: '', type: '', city: '', website: '', note: '', isVerified: false };

export function CompaniesPage() {
  const { db, upsertCompany, deleteCompany } = useApp();
  const [draft, setDraft] = useState(blank);

  function edit(company) { setDraft(company); }
  function patch(key, value) { setDraft((prev) => ({ ...prev, [key]: value })); }
  function save() { upsertCompany(draft); setDraft(blank); }

  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Admin CRUD" title="Компании" subtitle="Создание, редактирование и удаление компаний в системе." />
      <div className="two-col-grid">
        <Card>
          <div className="stack-md">
            <h3>{draft.id ? 'Редактировать компанию' : 'Новая компания'}</h3>
            <FieldGrid>
              <Input label="Название" value={draft.name} onChange={(e) => patch('name', e.target.value)} />
              <Input label="Тип" value={draft.type} onChange={(e) => patch('type', e.target.value)} />
              <Input label="Город" value={draft.city} onChange={(e) => patch('city', e.target.value)} />
              <Input label="Сайт" value={draft.website} onChange={(e) => patch('website', e.target.value)} />
            </FieldGrid>
            <Textarea label="Заметка" rows={4} value={draft.note} onChange={(e) => patch('note', e.target.value)} />
            <label className="checkbox-row"><input type="checkbox" checked={draft.isVerified} onChange={(e) => patch('isVerified', e.target.checked)} /> Verified</label>
            <div className="actions-row"><Button onClick={save}>Сохранить</Button><Button variant="secondary" onClick={() => setDraft(blank)}>Сбросить</Button></div>
          </div>
        </Card>
        <Card>
          <div className="stack-md">
            <h3>Список компаний</h3>
            {db.companies.length === 0 ? <EmptyState title="Компаний нет" /> : db.companies.map((company) => (
              <div key={company.id} className="table-row cardish">
                <div><strong>{company.name}</strong><div className="muted small">{company.type} · {company.city}</div></div>
                <div className="actions-row wrap"><Button variant="secondary" className="mini" onClick={() => edit(company)}>Редактировать</Button><Button variant="danger" className="mini" onClick={() => deleteCompany(company.id)}>Удалить</Button></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
