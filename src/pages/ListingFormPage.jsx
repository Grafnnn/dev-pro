import React, { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Button, Card, FieldGrid, Input, PageHeader, Select, Textarea } from '../components/ui';

function emptyDraft(currentUser) {
  return {
    title: '', type: 'ЗУ', strategy: 'МЖС', region: 'Москва', district: '', address: '', area: '', price: '', priceType: 'Фиксированная цена',
    format: 'Public', privacy: 'NDA', score: '75', risk: 'Средний', teaser: '', description: '', summary: '',
    image: 'https://images.unsplash.com/photo-1511818966892-d7d671e672a2?q=80&w=1600&auto=format&fit=crop', tags: [], tagInput: '',
    documents: [], docName: '', docCategory: 'Legal', docAccess: 'public', docSize: '1.0 MB', status: 'draft', ownerId: currentUser?.id, companyId: currentUser?.companyId
  };
}

export function ListingFormPage() {
  const navigate = useNavigate();
  const { listingId } = useParams();
  const { currentUser, listingById, upsertListing } = useApp();
  const original = listingId ? listingById(listingId) : null;
  const [draft, setDraft] = useState(original ? { ...original, tagInput: '', docName: '', docCategory: 'Legal', docAccess: 'public', docSize: '1.0 MB' } : emptyDraft(currentUser));

  const isEdit = useMemo(() => Boolean(original), [original]);
  function patch(key, value) { setDraft((prev) => ({ ...prev, [key]: value })); }
  function addTag() {
    const tag = draft.tagInput.trim();
    if (!tag || draft.tags.includes(tag)) return;
    patch('tags', [...draft.tags, tag]);
    patch('tagInput', '');
  }
  function removeTag(tag) { patch('tags', draft.tags.filter((x) => x !== tag)); }
  function addDocument() {
    if (!draft.docName.trim()) return;
    patch('documents', [...draft.documents, { id: `temp-${Date.now()}`, name: draft.docName, category: draft.docCategory, access: draft.docAccess, size: draft.docSize }]);
    patch('docName', '');
  }
  function removeDocument(id) { patch('documents', draft.documents.filter((x) => x.id !== id)); }
  function save(status) {
    const payload = { ...draft, score: Number(draft.score || 0), status };
    delete payload.tagInput; delete payload.docName; delete payload.docCategory; delete payload.docAccess; delete payload.docSize;
    const saved = upsertListing(payload, { action: isEdit ? 'UPDATE_LISTING_FORM' : 'CREATE_LISTING_FORM' });
    navigate(`/listings/${saved.id}`);
  }

  return (
    <div className="stack-xl">
      <PageHeader eyebrow={isEdit ? 'Edit Listing' : 'Create Listing'} title={isEdit ? 'Редактирование лота' : 'Создание нового лота'} subtitle="Заполните карточку, настройте data room и сохраните в draft или moderation." />
      <div className="two-col-grid listing-form-grid">
        <Card>
          <div className="stack-lg">
            <FieldGrid>
              <Input label="Название" value={draft.title} onChange={(e) => patch('title', e.target.value)} />
              <Select label="Тип" value={draft.type} onChange={(e) => patch('type', e.target.value)} options={['ЗУ', 'Редевелопмент', 'Объект']} />
              <Select label="Стратегия" value={draft.strategy} onChange={(e) => patch('strategy', e.target.value)} options={['МЖС', 'Mixed-use', 'Industrial', 'Retail', 'КРТ', 'Апарты']} />
              <Select label="Регион" value={draft.region} onChange={(e) => patch('region', e.target.value)} options={['Москва', 'МО', 'Санкт-Петербург']} />
              <Input label="Район" value={draft.district} onChange={(e) => patch('district', e.target.value)} />
              <Input label="Адрес" value={draft.address} onChange={(e) => patch('address', e.target.value)} />
              <Input label="Площадь, га" value={draft.area} onChange={(e) => patch('area', e.target.value)} />
              <Input label="Цена, млн ₽" value={draft.price} onChange={(e) => patch('price', e.target.value)} />
              <Select label="Формат цены" value={draft.priceType} onChange={(e) => patch('priceType', e.target.value)} options={['Фиксированная цена', 'Индикатив', 'По запросу']} />
              <Select label="Формат размещения" value={draft.format} onChange={(e) => patch('format', e.target.value)} options={['Public', 'Private', 'Exclusive']} />
              <Select label="Приватность" value={draft.privacy} onChange={(e) => patch('privacy', e.target.value)} options={['Public', 'Request', 'NDA']} />
              <Input label="Скоринг" value={draft.score} onChange={(e) => patch('score', e.target.value)} />
              <Select label="Риск" value={draft.risk} onChange={(e) => patch('risk', e.target.value)} options={['Низкий', 'Средний', 'Выше среднего', 'Высокий']} />
              <Input label="URL изображения" value={draft.image} onChange={(e) => patch('image', e.target.value)} />
            </FieldGrid>
            <Textarea label="Teaser" rows={3} value={draft.teaser} onChange={(e) => patch('teaser', e.target.value)} />
            <Textarea label="Описание" rows={4} value={draft.description} onChange={(e) => patch('description', e.target.value)} />
            <Textarea label="Investment summary" rows={4} value={draft.summary} onChange={(e) => patch('summary', e.target.value)} />
            <div className="tag-editor">
              <Input label="Тег" value={draft.tagInput} onChange={(e) => patch('tagInput', e.target.value)} />
              <Button variant="secondary" onClick={addTag}>Добавить тег</Button>
              <div className="tag-row">{draft.tags.map((tag) => <button key={tag} className="tag-chip button-chip" onClick={() => removeTag(tag)}>#{tag} ×</button>)}</div>
            </div>
            <div className="actions-row"><Button variant="secondary" onClick={() => save('draft')}>Сохранить draft</Button><Button onClick={() => save('moderation')}>Отправить на модерацию</Button></div>
          </div>
        </Card>
        <Card>
          <div className="stack-lg">
            <h3>Документы data room</h3>
            <FieldGrid columns={4}>
              <Input label="Название" value={draft.docName} onChange={(e) => patch('docName', e.target.value)} />
              <Select label="Категория" value={draft.docCategory} onChange={(e) => patch('docCategory', e.target.value)} options={['Legal', 'Urban Planning', 'Technical', 'Marketing', 'Financial']} />
              <Select label="Доступ" value={draft.docAccess} onChange={(e) => patch('docAccess', e.target.value)} options={['public', 'nda', 'approved']} />
              <Input label="Размер" value={draft.docSize} onChange={(e) => patch('docSize', e.target.value)} />
            </FieldGrid>
            <Button variant="secondary" onClick={addDocument}>Добавить документ</Button>
            <div className="stack-sm">
              {draft.documents.map((doc) => (
                <div key={doc.id} className="table-row cardish"><div><strong>{doc.name}</strong><div className="muted small">{doc.category} · {doc.size}</div></div><div className="actions-row"><span className="mini-pill">{doc.access}</span><Button variant="danger" className="mini" onClick={() => removeDocument(doc.id)}>Удалить</Button></div></div>
              ))}
            </div>
            <h3>Предпросмотр</h3>
            <img src={draft.image} alt={draft.title} className="preview-image" />
            <div className="stack-sm"><strong>{draft.title || 'Новый лот'}</strong><p className="muted">{draft.region} · {draft.district}</p><p>{draft.teaser}</p></div>
          </div>
        </Card>
      </div>
    </div>
  );
}
