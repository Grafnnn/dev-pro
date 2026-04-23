import React, { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { accessForListing, visibleDocuments } from '../lib/helpers';
import { Badge, Button, Card, Input, PageHeader, Textarea } from '../components/ui';

export function ListingDetailPage() {
  const { listingId } = useParams();
  const { db, currentUser, listingById, companyName, userName, requestAccess, submitOffer, submitQuestion } = useApp();
  const listing = listingById(listingId);
  const access = useMemo(() => accessForListing(db, listingId, currentUser), [db, listingId, currentUser]);
  const docs = listing ? visibleDocuments(listing, access.level) : [];
  const [requestMessage, setRequestMessage] = useState('');
  const [offerAmount, setOfferAmount] = useState('');
  const [offerComment, setOfferComment] = useState('');
  const [question, setQuestion] = useState('');

  if (!listing) return <Card><div className="empty-state"><h3>Лот не найден</h3></div></Card>;

  return (
    <div className="stack-xl">
      <PageHeader
        eyebrow="Listing Detail"
        title={listing.title}
        subtitle={`${listing.region}, ${listing.district} · ${companyName(listing.companyId)} · менеджер: ${userName(listing.ownerId)}`}
        actions={<Link className="btn btn-secondary" to="/marketplace">Назад</Link>}
      />

      <div className="detail-grid">
        <Card className="detail-main">
          <img src={listing.image} alt={listing.title} className="detail-cover" />
          <div className="stack-lg">
            <div className="badges-row">
              <Badge tone={listing.verified ? 'success' : 'warn'}>{listing.verified ? 'Проверенный актив' : 'Без верификации'}</Badge>
              <Badge>{listing.type}</Badge>
              <Badge>{listing.strategy}</Badge>
              <Badge tone="blue">{listing.privacy}</Badge>
            </div>
            <p>{listing.description}</p>
            <Card className="subcard">
              <strong>Investment summary</strong>
              <p className="muted">{listing.summary}</p>
            </Card>
            <div className="metric-inline-grid four">
              <div><span>Площадь</span><strong>{listing.area} га</strong></div>
              <div><span>Цена</span><strong>{listing.price} млн ₽</strong></div>
              <div><span>Скоринг</span><strong>{listing.score} / 100</strong></div>
              <div><span>Риск</span><strong>{listing.risk}</strong></div>
            </div>
            <div className="tag-row">{(listing.tags || []).map((tag) => <span key={tag} className="tag-chip">#{tag}</span>)}</div>
          </div>
        </Card>

        <div className="stack-lg">
          <Card>
            <div className="section-title-row">
              <h3>Data room</h3>
              <Badge tone={access.level === 'approved' ? 'success' : access.level === 'nda' ? 'blue' : 'default'}>{access.level}</Badge>
            </div>
            <div className="stack-sm">
              {docs.map((doc) => (
                <div key={doc.id} className="table-row lite">
                  <div>
                    <strong>{doc.name}</strong>
                    <div className="muted small">{doc.category}</div>
                  </div>
                  <Badge>{doc.access}</Badge>
                </div>
              ))}
              {docs.length === 0 && <div className="muted">Документы откроются после NDA / approval.</div>}
            </div>
          </Card>

          {(currentUser?.role === 'investor' || currentUser?.role === 'developer') && (
            <>
              <Card>
                <h3>NDA / Access request</h3>
                <Textarea label="Комментарий к запросу" value={requestMessage} onChange={(e) => setRequestMessage(e.target.value)} rows={3} />
                <Button onClick={() => requestAccess(listing.id, requestMessage)}>Подтвердить NDA и запросить доступ</Button>
              </Card>
              <Card>
                <h3>Indicative offer</h3>
                <Input label="Сумма, млн ₽" value={offerAmount} onChange={(e) => setOfferAmount(e.target.value)} />
                <Textarea label="Комментарий" value={offerComment} onChange={(e) => setOfferComment(e.target.value)} rows={3} />
                <Button onClick={() => submitOffer(listing.id, offerAmount, offerComment)}>Отправить offer</Button>
              </Card>
              <Card>
                <h3>Вопрос по лоту</h3>
                <Textarea label="Вопрос" value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} />
                <Button onClick={() => submitQuestion(listing.id, question)}>Отправить вопрос</Button>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
