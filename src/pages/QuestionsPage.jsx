import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { Button, Card, EmptyState, PageHeader, Textarea } from '../components/ui';

export function QuestionsPage() {
  const { db, currentUser, answerQuestion, userName } = useApp();
  const [drafts, setDrafts] = useState({});
  const questions = currentUser.role === 'admin'
    ? db.questions
    : db.questions.filter((x) => x.ownerId === currentUser.id || db.listings.find((l) => l.id === x.listingId)?.ownerId === currentUser.id);

  function patch(id, value) {
    setDrafts((prev) => ({ ...prev, [id]: value }));
  }

  return (
    <div className="stack-xl">
      <PageHeader eyebrow="Questions Desk" title="Вопросы по лотам" subtitle="Продавец может отвечать на вопросы прямо из кабинета, не выходя во внешний чат." />
      <Card>
        <div className="stack-md">
          {questions.length === 0 ? <EmptyState title="Новых вопросов нет" /> : questions.map((item) => {
            const listing = db.listings.find((x) => x.id === item.listingId);
            return (
              <div key={item.id} className="question-card">
                <div className="question-meta">
                  <Link to={`/listings/${item.listingId}`}><strong>{listing?.title}</strong></Link>
                  <span className="muted small">{item.createdAt} · {userName(item.userId)}</span>
                </div>
                <div className="question-box">{item.question}</div>
                <Textarea label="Ответ" rows={3} value={drafts[item.id] ?? item.answer} onChange={(e) => patch(item.id, e.target.value)} />
                <div className="actions-row">
                  <Button onClick={() => answerQuestion(item.id, drafts[item.id] ?? item.answer)}>Сохранить ответ</Button>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
