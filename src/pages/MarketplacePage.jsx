import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Badge, Button, Card, EmptyState, Input, PageHeader, Select } from '../components/ui';

export function MarketplacePage() {
  const { db, favorites, compare, toggleFavorite, toggleCompare } = useApp();
  const [search, setSearch] = useState('');
  const [region, setRegion] = useState('Все');
  const [type, setType] = useState('Все');

  const listings = useMemo(() => db.listings.filter((item) => {
    if (item.status !== 'published') return false;
    const hay = [item.title, item.region, item.district, item.strategy, item.type, ...(item.tags || [])].join(' ').toLowerCase();
    return hay.includes(search.toLowerCase()) && (region === 'Все' || item.region === region) && (type === 'Все' || item.type === type);
  }), [db.listings, search, region, type]);

  return (
    <div className="stack-xl">
      <PageHeader
        eyebrow="Marketplace"
        title="Каталог девелоперских активов"
        subtitle="Фильтруйте лоты, собирайте shortlist, добавляйте активы в compare и переходите в карточку сделки."
        actions={
          <div className="actions-row">
            <Badge tone="blue">Shortlist: {favorites.length}</Badge>
            <Badge tone="blue">Compare: {compare.length}</Badge>
          </div>
        }
      />

      <Card>
        <div className="toolbar-grid">
          <Input label="Поиск" placeholder="По названию, тегам, району, стратегии" value={search} onChange={(e) => setSearch(e.target.value)} />
          <Select label="Регион" value={region} onChange={(e) => setRegion(e.target.value)} options={['Все', 'Москва', 'МО', 'Санкт-Петербург']} />
          <Select label="Тип" value={type} onChange={(e) => setType(e.target.value)} options={['Все', 'ЗУ', 'Редевелопмент', 'Объект']} />
        </div>
      </Card>

      {listings.length === 0 ? (
        <EmptyState title="По фильтрам ничего не найдено" subtitle="Измените фильтры или сбросьте поисковый запрос." />
      ) : (
        <div className="cards-grid">
          {listings.map((item) => (
            <Card key={item.id} className="listing-card">
              <img src={item.image} alt={item.title} className="listing-cover" />
              <div className="stack-md">
                <div className="badges-row">
                  <Badge tone={item.verified ? 'success' : 'warn'}>{item.verified ? 'Проверен' : 'Без верификации'}</Badge>
                  <Badge>{item.type}</Badge>
                  <Badge>{item.strategy}</Badge>
                </div>
                <div>
                  <h3>{item.title}</h3>
                  <p className="muted">{item.region}, {item.district}</p>
                </div>
                <p className="muted">{item.teaser}</p>
                <div className="metric-inline-grid">
                  <div><span>Площадь</span><strong>{item.area} га</strong></div>
                  <div><span>Цена</span><strong>{item.price} млн ₽</strong></div>
                  <div><span>Скоринг</span><strong>{item.score} / 100</strong></div>
                </div>
                <div className="tag-row">
                  {(item.tags || []).map((tag) => <span key={tag} className="tag-chip">#{tag}</span>)}
                </div>
                <div className="actions-row">
                  <Link className="btn btn-primary" to={`/listings/${item.id}`}>Открыть</Link>
                  <Button variant={favorites.includes(item.id) ? 'danger' : 'secondary'} onClick={() => toggleFavorite(item.id)}>{favorites.includes(item.id) ? 'Убрать' : 'Shortlist'}</Button>
                  <Button variant={compare.includes(item.id) ? 'primary' : 'secondary'} onClick={() => toggleCompare(item.id)}>{compare.includes(item.id) ? 'В compare' : 'Compare'}</Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
