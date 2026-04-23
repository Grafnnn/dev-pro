import React from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Card, EmptyState, MetricCard, PageHeader } from '../components/ui';

export function InvestorDashboardPage() {
  const { db, currentUser, favorites, compare } = useApp();
  const shortlist = db.listings.filter((x) => favorites.includes(x.id));
  const compareItems = db.listings.filter((x) => compare.includes(x.id));
  const myRequests = db.accessRequests.filter((x) => x.requesterId === currentUser.id);
  const myOffers = db.offers.filter((x) => x.userId === currentUser.id);

  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Investor Workspace" title={`Dashboard: ${currentUser.name}`} subtitle="Подборки, запросы доступа, compare workspace и офферы в одном месте." />
      <div className="metrics-grid four">
        <MetricCard label="Shortlist" value={shortlist.length} />
        <MetricCard label="Compare" value={compareItems.length} />
        <MetricCard label="Запросы" value={myRequests.length} />
        <MetricCard label="Offers" value={myOffers.length} />
      </div>
      <div className="two-col-grid">
        <Card>
          <div className="section-title-row"><h3>Моя shortlist</h3><Link className="btn btn-secondary" to="/marketplace">Открыть маркетплейс</Link></div>
          <div className="stack-sm">
            {shortlist.length === 0 ? <EmptyState title="Пока пусто" subtitle="Добавьте лоты в shortlist из маркетплейса." /> : shortlist.map((item) => (
              <Link key={item.id} to={`/listings/${item.id}`} className="table-row interactive"><div><strong>{item.title}</strong><div className="muted small">{item.region} · {item.strategy}</div></div><strong>{item.price} млн ₽</strong></Link>
            ))}
          </div>
        </Card>
        <Card>
          <div className="section-title-row"><h3>Compare workspace</h3><Link className="btn btn-primary" to="/compare">Открыть</Link></div>
          <div className="stack-sm">
            {compareItems.length === 0 ? <EmptyState title="Нет активов для сравнения" subtitle="Добавьте 2–4 актива в compare." /> : compareItems.map((item) => (
              <div key={item.id} className="table-row"><div><strong>{item.title}</strong><div className="muted small">{item.type} · {item.area} га</div></div><strong>{item.score} / 100</strong></div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
