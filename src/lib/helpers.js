import { STAGE_LABELS } from '../data/seed';

export function accessForListing(db, listingId, user) {
  if (!user) return { level: 'public', status: null };
  const listing = db.listings.find((x) => x.id === listingId);
  if (!listing) return { level: 'public', status: null };
  if (listing.ownerId === user.id || user.role === 'admin') return { level: 'approved', status: 'approved' };
  const req = db.accessRequests.find((x) => x.listingId === listingId && x.requesterId === user.id);
  if (req?.status === 'approved') return { level: 'approved', status: req.status };
  if (req?.ndaAccepted) return { level: 'nda', status: req.status };
  return { level: 'public', status: req?.status || null };
}

export function visibleDocuments(listing, accessLevel) {
  return (listing.documents || []).filter((doc) => doc.access === 'public' || (doc.access === 'nda' && ['nda', 'approved'].includes(accessLevel)) || (doc.access === 'approved' && accessLevel === 'approved'));
}

export function stageLabel(stage) {
  return STAGE_LABELS[stage] || stage;
}

export function toneForStage(stage) {
  if (stage === 'won') return 'success';
  if (stage === 'lost') return 'warn';
  if (stage === 'offer' || stage === 'dd') return 'blue';
  return 'default';
}
