import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { loadState, resetState, saveState, uid } from '../lib/store';
import { ROLE_LABELS, STAGES } from '../data/seed';

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [db, setDb] = useState(() => loadState());
  const [session, setSession] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('devland_session'));
    } catch {
      return null;
    }
  });

  useEffect(() => {
    saveState(db);
  }, [db]);

  useEffect(() => {
    if (session) localStorage.setItem('devland_session', JSON.stringify(session));
    else localStorage.removeItem('devland_session');
  }, [session]);

  const currentUser = useMemo(() => db.users.find((u) => u.id === session?.userId) || null, [db.users, session]);
  const currentCompany = useMemo(() => db.companies.find((c) => c.id === currentUser?.companyId) || null, [db.companies, currentUser]);

  function audit(action, entity, actor = session?.userId || 'guest') {
    setDb((prev) => ({
      ...prev,
      auditLogs: [...prev.auditLogs, { id: uid('log'), action, entity, actor, createdAt: new Date().toLocaleString('ru-RU') }]
    }));
  }

  function login(email, password) {
    const user = db.users.find((u) => u.email.toLowerCase() === email.toLowerCase() && u.password === password && u.isActive !== false);
    if (!user) return { ok: false, message: 'Неверный email или пароль.' };
    setSession({ userId: user.id });
    audit('LOGIN', 'auth', user.id);
    return { ok: true, user };
  }

  function register(payload) {
    if (!payload.name || !payload.email || !payload.password) return { ok: false, message: 'Заполните обязательные поля.' };
    if (db.users.some((u) => u.email.toLowerCase() === payload.email.toLowerCase())) return { ok: false, message: 'Пользователь с таким email уже существует.' };
    let companyId = payload.companyId;
    const updates = { ...db };
    if (!companyId && payload.companyName) {
      companyId = uid('c');
      updates.companies = [...updates.companies, { id: companyId, name: payload.companyName, type: payload.role, city: payload.city || '', website: '', note: '', isVerified: false }];
    }
    const user = { id: uid('u'), name: payload.name, email: payload.email, password: payload.password, role: payload.role || 'investor', companyId: companyId || updates.companies[0]?.id, city: payload.city || '', phone: payload.phone || '', isActive: true };
    updates.users = [...updates.users, user];
    setDb(updates);
    setSession({ userId: user.id });
    audit('REGISTER', user.id, user.id);
    return { ok: true, user };
  }

  function logout() {
    if (session?.userId) audit('LOGOUT', 'auth', session.userId);
    setSession(null);
  }

  function companyName(companyId) {
    return db.companies.find((x) => x.id === companyId)?.name || '—';
  }

  function userName(userId) {
    return db.users.find((x) => x.id === userId)?.name || '—';
  }

  function listingById(id) {
    return db.listings.find((x) => x.id === id) || null;
  }

  function getFavorites() {
    return currentUser ? db.favoritesByUser[currentUser.id] || [] : [];
  }

  function getCompare() {
    return currentUser ? db.compareByUser[currentUser.id] || [] : [];
  }

  function toggleFavorite(listingId) {
    if (!currentUser) return;
    setDb((prev) => {
      const current = prev.favoritesByUser[currentUser.id] || [];
      const next = current.includes(listingId) ? current.filter((x) => x !== listingId) : [...current, listingId];
      return { ...prev, favoritesByUser: { ...prev.favoritesByUser, [currentUser.id]: next } };
    });
    audit('TOGGLE_FAVORITE', listingId);
  }

  function toggleCompare(listingId) {
    if (!currentUser) return;
    setDb((prev) => {
      const current = prev.compareByUser[currentUser.id] || [];
      let next = current.includes(listingId) ? current.filter((x) => x !== listingId) : [...current, listingId];
      if (next.length > 4) next = next.slice(next.length - 4);
      return { ...prev, compareByUser: { ...prev.compareByUser, [currentUser.id]: next } };
    });
    audit('TOGGLE_COMPARE', listingId);
  }

  function upsertCompany(company) {
    setDb((prev) => {
      const exists = prev.companies.some((x) => x.id === company.id);
      const next = exists
        ? prev.companies.map((x) => (x.id === company.id ? { ...x, ...company } : x))
        : [...prev.companies, { ...company, id: uid('c') }];
      return { ...prev, companies: next };
    });
    audit(company.id ? 'UPDATE_COMPANY' : 'CREATE_COMPANY', company.id || 'new-company');
  }

  function deleteCompany(companyId) {
    setDb((prev) => ({ ...prev, companies: prev.companies.filter((x) => x.id !== companyId) }));
    audit('DELETE_COMPANY', companyId);
  }

  function upsertUser(user) {
    setDb((prev) => {
      const exists = prev.users.some((x) => x.id === user.id);
      const next = exists
        ? prev.users.map((x) => (x.id === user.id ? { ...x, ...user } : x))
        : [...prev.users, { ...user, id: uid('u') }];
      return { ...prev, users: next };
    });
    audit(user.id ? 'UPDATE_USER' : 'CREATE_USER', user.id || 'new-user');
  }

  function deleteUser(userId) {
    setDb((prev) => ({ ...prev, users: prev.users.filter((x) => x.id !== userId) }));
    audit('DELETE_USER', userId);
  }

  function upsertListing(listing, options = {}) {
    const ownerId = listing.ownerId || currentUser?.id;
    const companyId = listing.companyId || currentUser?.companyId;
    const payload = {
      ...listing,
      ownerId,
      companyId,
      id: listing.id || uid('l'),
      verified: listing.verified ?? false,
      createdAt: listing.createdAt || new Date().toLocaleDateString('ru-RU'),
      documents: listing.documents || []
    };
    setDb((prev) => {
      const exists = prev.listings.some((x) => x.id === payload.id);
      const listings = exists ? prev.listings.map((x) => (x.id === payload.id ? { ...x, ...payload } : x)) : [...prev.listings, payload];
      return { ...prev, listings };
    });
    audit(options.action || (listing.id ? 'UPDATE_LISTING' : 'CREATE_LISTING'), payload.id);
    return payload;
  }

  function deleteListing(listingId) {
    setDb((prev) => ({
      ...prev,
      listings: prev.listings.filter((x) => x.id !== listingId),
      accessRequests: prev.accessRequests.filter((x) => x.listingId !== listingId),
      offers: prev.offers.filter((x) => x.listingId !== listingId),
      questions: prev.questions.filter((x) => x.listingId !== listingId),
      deals: prev.deals.filter((x) => x.listingId !== listingId)
    }));
    audit('DELETE_LISTING', listingId);
  }

  function addDocument(listingId, document) {
    setDb((prev) => ({
      ...prev,
      listings: prev.listings.map((x) => x.id === listingId ? { ...x, documents: [...(x.documents || []), { ...document, id: uid('d') }] } : x)
    }));
    audit('ADD_DOCUMENT', listingId);
  }

  function removeDocument(listingId, documentId) {
    setDb((prev) => ({
      ...prev,
      listings: prev.listings.map((x) => x.id === listingId ? { ...x, documents: (x.documents || []).filter((d) => d.id !== documentId) } : x)
    }));
    audit('REMOVE_DOCUMENT', `${listingId}:${documentId}`);
  }

  function requestAccess(listingId, message) {
    if (!currentUser) return;
    const listing = listingById(listingId);
    const existing = db.accessRequests.find((x) => x.listingId === listingId && x.requesterId === currentUser.id);
    if (existing) {
      setDb((prev) => ({
        ...prev,
        accessRequests: prev.accessRequests.map((x) => x.id === existing.id ? { ...x, message: message || x.message, ndaAccepted: true, status: x.status === 'approved' ? 'approved' : 'pending' } : x)
      }));
    } else {
      setDb((prev) => ({
        ...prev,
        accessRequests: [...prev.accessRequests, { id: uid('ar'), listingId, requesterId: currentUser.id, ownerId: listing?.ownerId, message: message || '', status: 'pending', ndaAccepted: true, createdAt: new Date().toLocaleString('ru-RU') }]
      }));
    }
    ensureDeal(listingId, currentUser.companyId, listing?.ownerId, 'nda');
    audit('REQUEST_ACCESS', listingId);
  }

  function approveRequest(id) {
    setDb((prev) => ({ ...prev, accessRequests: prev.accessRequests.map((x) => x.id === id ? { ...x, status: 'approved' } : x) }));
    const request = db.accessRequests.find((x) => x.id === id);
    if (request) ensureDeal(request.listingId, db.users.find((u) => u.id === request.requesterId)?.companyId, request.ownerId, 'review');
    audit('APPROVE_REQUEST', id);
  }

  function rejectRequest(id) {
    setDb((prev) => ({ ...prev, accessRequests: prev.accessRequests.map((x) => x.id === id ? { ...x, status: 'rejected' } : x) }));
    audit('REJECT_REQUEST', id);
  }

  function submitOffer(listingId, amount, comment) {
    if (!currentUser || !amount) return;
    setDb((prev) => ({ ...prev, offers: [...prev.offers, { id: uid('of'), listingId, userId: currentUser.id, amount, comment, status: 'received', createdAt: new Date().toLocaleString('ru-RU') }] }));
    ensureDeal(listingId, currentUser.companyId, listingById(listingId)?.ownerId, 'offer', amount);
    audit('SUBMIT_OFFER', listingId);
  }

  function submitQuestion(listingId, question) {
    if (!currentUser || !question.trim()) return;
    const listing = listingById(listingId);
    setDb((prev) => ({ ...prev, questions: [...prev.questions, { id: uid('q'), listingId, userId: currentUser.id, ownerId: listing?.ownerId, question, answer: '', createdAt: new Date().toLocaleString('ru-RU') }] }));
    ensureDeal(listingId, currentUser.companyId, listing?.ownerId, 'review');
    audit('ASK_QUESTION', listingId);
  }

  function answerQuestion(questionId, answer) {
    setDb((prev) => ({ ...prev, questions: prev.questions.map((x) => x.id === questionId ? { ...x, answer } : x) }));
    audit('ANSWER_QUESTION', questionId);
  }

  function ensureDeal(listingId, companyId, ownerId, stage = 'new', amount = '') {
    if (!companyId) return;
    setDb((prev) => {
      const listing = prev.listings.find((x) => x.id === listingId);
      const existing = prev.deals.find((x) => x.listingId === listingId && x.companyId === companyId);
      if (existing) {
        return {
          ...prev,
          deals: prev.deals.map((x) => x.id === existing.id ? { ...x, stage: STAGES.indexOf(stage) > STAGES.indexOf(x.stage) ? stage : x.stage, amount: amount || x.amount, updatedAt: new Date().toLocaleString('ru-RU') } : x)
        };
      }
      return {
        ...prev,
        deals: [...prev.deals, { id: uid('deal'), listingId, companyId, ownerId, title: `${listing?.title || 'Лот'} / ${companyName(companyId)}`, stage, amount: amount || listing?.price || '', nextStep: '', updatedAt: new Date().toLocaleString('ru-RU') }]
      };
    });
  }

  function upsertDeal(deal) {
    setDb((prev) => {
      const exists = prev.deals.some((x) => x.id === deal.id);
      const next = exists ? prev.deals.map((x) => (x.id === deal.id ? { ...x, ...deal, updatedAt: new Date().toLocaleString('ru-RU') } : x)) : [...prev.deals, { ...deal, id: uid('deal'), updatedAt: new Date().toLocaleString('ru-RU') }];
      return { ...prev, deals: next };
    });
    audit(deal.id ? 'UPDATE_DEAL' : 'CREATE_DEAL', deal.id || 'new-deal');
  }

  function moveDeal(dealId, stage) {
    setDb((prev) => ({ ...prev, deals: prev.deals.map((x) => x.id === dealId ? { ...x, stage, updatedAt: new Date().toLocaleString('ru-RU') } : x) }));
    audit('MOVE_DEAL', `${dealId}:${stage}`);
  }

  function deleteDeal(dealId) {
    setDb((prev) => ({ ...prev, deals: prev.deals.filter((x) => x.id !== dealId) }));
    audit('DELETE_DEAL', dealId);
  }

  function exportState() {
    const blob = new Blob([JSON.stringify(db, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'devland-export.json';
    a.click();
    URL.revokeObjectURL(url);
    audit('EXPORT_STATE', 'database');
  }

  function hardReset() {
    const next = resetState();
    setDb(next);
    audit('RESET_STATE', 'database');
  }

  const value = {
    db,
    currentUser,
    currentCompany,
    ROLE_LABELS,
    login,
    register,
    logout,
    companyName,
    userName,
    listingById,
    favorites: getFavorites(),
    compare: getCompare(),
    toggleFavorite,
    toggleCompare,
    upsertCompany,
    deleteCompany,
    upsertUser,
    deleteUser,
    upsertListing,
    deleteListing,
    addDocument,
    removeDocument,
    requestAccess,
    approveRequest,
    rejectRequest,
    submitOffer,
    submitQuestion,
    answerQuestion,
    upsertDeal,
    moveDeal,
    deleteDeal,
    exportState,
    hardReset,
    audit,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside AppProvider');
  return ctx;
}
