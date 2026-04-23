import React from 'react';
import { Link } from 'react-router-dom';

export function clsx(...items) {
  return items.filter(Boolean).join(' ');
}

export function Card({ children, className = '' }) {
  return <div className={clsx('card', className)}>{children}</div>;
}

export function Button({ children, variant = 'primary', className = '', ...props }) {
  return <button className={clsx('btn', `btn-${variant}`, className)} {...props}>{children}</button>;
}

export function Input({ label, className = '', ...props }) {
  return (
    <label className="field">
      {label && <span className="field-label">{label}</span>}
      <input className={clsx('input', className)} {...props} />
    </label>
  );
}

export function Select({ label, options = [], className = '', ...props }) {
  return (
    <label className="field">
      {label && <span className="field-label">{label}</span>}
      <select className={clsx('input', className)} {...props}>
        {options.map((option) => (
          <option key={option.value ?? option} value={option.value ?? option}>{option.label ?? option}</option>
        ))}
      </select>
    </label>
  );
}

export function Textarea({ label, className = '', ...props }) {
  return (
    <label className="field">
      {label && <span className="field-label">{label}</span>}
      <textarea className={clsx('input textarea', className)} {...props} />
    </label>
  );
}

export function Badge({ children, tone = 'default' }) {
  return <span className={clsx('badge', `badge-${tone}`)}>{children}</span>;
}

export function PageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function MetricCard({ label, value, meta }) {
  return (
    <Card className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {meta && <div className="metric-meta">{meta}</div>}
    </Card>
  );
}

export function EmptyState({ title, subtitle, action }) {
  return (
    <Card className="empty-state">
      <h3>{title}</h3>
      {subtitle && <p>{subtitle}</p>}
      {action}
    </Card>
  );
}

export function FieldGrid({ children, columns = 2 }) {
  return <div className={`field-grid columns-${columns}`}>{children}</div>;
}

export function Divider() {
  return <div className="divider" />;
}

export function LinkButton({ to, children, variant = 'secondary', className = '' }) {
  return <Link to={to} className={clsx('btn', `btn-${variant}`, className)}>{children}</Link>;
}
