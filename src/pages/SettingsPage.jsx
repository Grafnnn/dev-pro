import React from 'react';
import { useApp } from '../context/AppContext';
import { Button, Card, PageHeader } from '../components/ui';

export function SettingsPage() {
  const { exportState, hardReset, currentUser, currentCompany } = useApp();
  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Settings" title="Сервисные действия" subtitle="Экспорт данных и сброс демо-среды для нового цикла тестирования." />
      <div className="two-col-grid">
        <Card>
          <div className="stack-md">
            <h3>Текущий пользователь</h3>
            <div className="table-row"><span>Имя</span><strong>{currentUser?.name}</strong></div>
            <div className="table-row"><span>Роль</span><strong>{currentUser?.role}</strong></div>
            <div className="table-row"><span>Компания</span><strong>{currentCompany?.name}</strong></div>
          </div>
        </Card>
        <Card>
          <div className="stack-md">
            <h3>Управление данными</h3>
            <p className="muted">Экспортируйте JSON базы для передачи в Codex или разработки. Сброс вернет seed-данные.</p>
            <div className="actions-row wrap">
              <Button onClick={exportState}>Экспортировать JSON</Button>
              <Button variant="danger" onClick={hardReset}>Сбросить demo data</Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
