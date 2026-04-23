import React from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Badge, Button, Card, EmptyState, PageHeader } from '../components/ui';

export function RequestsPage() {
  const { db, currentUser, approveRequest, rejectRequest } = useApp();
  const requests = currentUser.role === 'admin'
    ? db.accessRequests
    : ['seller', 'broker'].includes(currentUser.role)
    ? db.accessRequests.filter((x) => x.ownerId === currentUser.id)
    : db.accessRequests.filter((x) => x.requesterId === currentUser.id);

  return (
    <div className="stack-xl">
      <PageHeader eyebrow="NDA / Access" title="Запросы доступа" subtitle="Видно, кто и к каким активам запросил доступ, а также статус NDA и approval." />
      <Card>
        <div className="stack-md">
          {requests.length === 0 ? <EmptyState title="Нет запросов" /> : requests.map((req) => {
            const listing = db.listings.find((x) => x.id === req.listingId);
            const company = db.companies.find((x) => x.id === db.users.find((u) => u.id === req.requesterId)?.companyId);
            return (
              <div key={req.id} className="table-row cardish">
                <div>
                  <Link to={`/listings/${listing?.id}`}><strong>{listing?.title}</strong></Link>
                  <div className="muted small">{company?.name || '—'} · {req.createdAt}</div>
                  <div className="muted">{req.message}</div>
                </div>
                <div className="actions-row wrap">
                  <Badge tone={req.ndaAccepted ? 'success' : 'warn'}>{req.ndaAccepted ? 'NDA OK' : 'NDA missing'}</Badge>
                  <Badge tone={req.status === 'approved' ? 'success' : req.status === 'rejected' ? 'warn' : 'blue'}>{req.status}</Badge>
                  {['seller', 'broker', 'admin'].includes(currentUser.role) && req.status === 'pending' && (
                    <>
                      <Button variant="secondary" onClick={() => rejectRequest(req.id)}>Reject</Button>
                      <Button variant="success" onClick={() => approveRequest(req.id)}>Approve</Button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
