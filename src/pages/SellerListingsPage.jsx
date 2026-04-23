import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Badge, Button, Card, EmptyState, Input, PageHeader, Select } from '../components/ui';

export function SellerListingsPage() {
  const { db, currentUser, deleteListing, upsertListing } = useApp();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('Все');

  const rows = useMemo(() => db.listings.filter((item) => {
    if (currentUser.role !== 'admin' && item.ownerId !== currentUser.id) return false;
    const hay = [item.title, item.region, item.type, item.strategy].join(' ').toLowerCase();
    return hay.includes(search.toLowerCase()) && (status === 'Все' || item.status === status);
  }), [db.listings, search, status, currentUser]);

  function quickPublish(item) {
    upsertListing({ ...item, status: 'published', verified: true }, { action: 'QUICK_PUBLISH' });
  }

  return (
    <div className="stack-xl">
      <PageHeader
        eyebrow="CRM Listings"
        title="Таблица лотов"
        subtitle="Полноценный CRM-style список активов с поиском, фильтрами, статусами и быстрыми действиями."
        actions={<Link className="btn btn-primary" to="/crm/listings/new">Создать лот</Link>}
      />
      <Card>
        <div className="toolbar-grid">
          <Input label="Поиск" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Название, регион, стратегия" />
          <Select label="Статус" value={status} onChange={(e) => setStatus(e.target.value)} options={['Все', 'draft', 'moderation', 'published', 'needs_fix']} />
        </div>
      </Card>
      <Card>
        {rows.length === 0 ? <EmptyState title="Лотов не найдено" /> : (
          <div className="table-wrap">
            <table className="crm-table">
              <thead>
                <tr>
                  <th>Лот</th>
                  <th>География</th>
                  <th>Параметры</th>
                  <th>Статус</th>
                  <th>Приватность</th>
                  <th>Документы</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.title}</strong>
                      <div className="muted small">{item.type} · {item.strategy}</div>
                    </td>
                    <td>{item.region}, {item.district}</td>
                    <td>{item.area} га · {item.price} млн ₽</td>
                    <td><Badge tone={item.status === 'published' ? 'success' : item.status === 'needs_fix' ? 'warn' : 'blue'}>{item.status}</Badge></td>
                    <td><Badge>{item.privacy}</Badge></td>
                    <td>{(item.documents || []).length}</td>
                    <td>
                      <div className="actions-row wrap">
                        <Link className="btn btn-secondary mini" to={`/listings/${item.id}`}>Открыть</Link>
                        <Link className="btn btn-secondary mini" to={`/crm/listings/${item.id}/edit`}>Редактировать</Link>
                        {item.status !== 'published' && <Button className="mini" onClick={() => quickPublish(item)}>Publish</Button>}
                        <Button variant="danger" className="mini" onClick={() => deleteListing(item.id)}>Удалить</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
