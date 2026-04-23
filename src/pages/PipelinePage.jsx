import React from 'react';
import { useApp } from '../context/AppContext';
import { STAGES, STAGE_LABELS } from '../data/seed';
import { stageLabel } from '../lib/helpers';
import { Badge, Button, Card, EmptyState, PageHeader } from '../components/ui';

export function PipelinePage() {
  const { db, currentUser, companyName, moveDeal } = useApp();
  const deals = currentUser.role === 'admin' ? db.deals : db.deals.filter((x) => x.ownerId === currentUser.id);

  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Pipeline / Kanban" title="Воронка лидов и сделок" subtitle="Канбан по стадиям: от нового лида до DD, win или loss." />
      {deals.length === 0 ? <EmptyState title="Сделок пока нет" /> : (
        <div className="kanban-grid">
          {STAGES.map((stage, index) => {
            const column = deals.filter((x) => x.stage === stage);
            return (
              <Card key={stage} className="kanban-column">
                <div className="kanban-header"><strong>{STAGE_LABELS[stage]}</strong><Badge>{column.length}</Badge></div>
                <div className="stack-sm">
                  {column.map((deal) => (
                    <div key={deal.id} className="kanban-card">
                      <div className="stack-sm">
                        <strong>{deal.title}</strong>
                        <div className="muted small">{companyName(deal.companyId)}</div>
                        <div className="muted small">{deal.amount} млн ₽</div>
                        <div className="muted small">Next: {deal.nextStep || '—'}</div>
                        <div className="actions-row wrap">
                          {index > 0 && <Button variant="secondary" className="mini" onClick={() => moveDeal(deal.id, STAGES[index - 1])}>← {stageLabel(STAGES[index - 1])}</Button>}
                          {index < STAGES.length - 1 && <Button className="mini" onClick={() => moveDeal(deal.id, STAGES[index + 1])}>{stageLabel(STAGES[index + 1])} →</Button>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
