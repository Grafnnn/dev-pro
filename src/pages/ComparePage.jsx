import React from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Card, EmptyState, PageHeader } from '../components/ui';

export function ComparePage() {
  const { db, compare, toggleCompare } = useApp();
  const items = db.listings.filter((x) => compare.includes(x.id));
  const rows = [
    ['Тип', (x) => x.type],
    ['Стратегия', (x) => x.strategy],
    ['Регион', (x) => x.region],
    ['Район', (x) => x.district],
    ['Площадь', (x) => `${x.area} га`],
    ['Цена', (x) => `${x.price} млн ₽`],
    ['Скоринг', (x) => `${x.score} / 100`],
    ['Риск', (x) => x.risk],
    ['Приватность', (x) => x.privacy],
    ['Документы', (x) => String((x.documents || []).length)]
  ];

  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Compare" title="Сравнение активов" subtitle="Табличное сопоставление ключевых параметров для investment committee." actions={<Link className="btn btn-secondary" to="/marketplace">Добавить лоты</Link>} />
      <Card>
        {items.length === 0 ? (
          <EmptyState title="Список compare пуст" subtitle="Добавьте активы из маркетплейса." />
        ) : (
          <div className="compare-table-wrap">
            <table className="compare-table">
              <thead>
                <tr>
                  <th>Параметр</th>
                  {items.map((item) => (
                    <th key={item.id}>
                      <div className="stack-sm">
                        <Link to={`/listings/${item.id}`}>{item.title}</Link>
                        <button className="mini-btn" onClick={() => toggleCompare(item.id)}>Убрать</button>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(([label, getter]) => (
                  <tr key={label}>
                    <td>{label}</td>
                    {items.map((item) => <td key={`${item.id}-${label}`}>{getter(item)}</td>)}
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
