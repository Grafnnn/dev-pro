import React from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Badge, Card, MetricCard, PageHeader } from '../components/ui';

export function AdminPage() {
  const { db } = useApp();
  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Admin Overview" title="Платформа под контролем" subtitle="Обзор сущностей, очереди модерации и последних действий системы." actions={<div className="actions-row"><Link className="btn btn-secondary" to="/admin/companies">Компании</Link><Link className="btn btn-secondary" to="/admin/users">Пользователи</Link></div>} />
      <div className="metrics-grid four">
        <MetricCard label="Компании" value={db.companies.length} />
        <MetricCard label="Пользователи" value={db.users.length} />
        <MetricCard label="Лоты" value={db.listings.length} />
        <MetricCard label="Audit logs" value={db.auditLogs.length} />
      </div>
      <div className="two-col-grid">
        <Card>
          <div className="section-title-row"><h3>Лоты на модерации</h3><Badge tone="blue">{db.listings.filter((x) => x.status === 'moderation' || x.status === 'needs_fix').length}</Badge></div>
          <div className="stack-sm">
            {db.listings.filter((x) => x.status === 'moderation' || x.status === 'needs_fix').map((item) => (
              <div key={item.id} className="table-row"><div><strong>{item.title}</strong><div className="muted small">{item.region} · {item.status}</div></div><Link className="btn btn-secondary mini" to={`/crm/listings/${item.id}/edit`}>Открыть</Link></div>
            ))}
          </div>
        </Card>
        <Card>
          <div className="section-title-row"><h3>Последние действия</h3></div>
          <div className="stack-sm">
            {db.auditLogs.slice().reverse().slice(0, 12).map((log) => (
              <div key={log.id} className="table-row"><div><strong>{log.action}</strong><div className="muted small">{log.entity}</div></div><span className="muted small">{log.createdAt}</span></div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
