import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { ROLE_LABELS } from '../data/seed';
import { clsx } from './ui';

function navItems(role) {
  const common = [
    { to: '/marketplace', label: 'Маркетплейс' },
    { to: '/requests', label: 'Запросы / NDA' },
    { to: '/settings', label: 'Настройки' },
  ];
  if (role === 'investor' || role === 'developer') {
    return [
      { to: '/dashboard', label: 'Dashboard' },
      { to: '/compare', label: 'Сравнение' },
      ...common,
    ];
  }
  if (role === 'seller' || role === 'broker') {
    return [
      { to: '/crm/listings', label: 'CRM / Лоты' },
      { to: '/crm/questions', label: 'Вопросы' },
      { to: '/crm/pipeline', label: 'Pipeline' },
      ...common,
    ];
  }
  return [
    { to: '/admin', label: 'Admin Overview' },
    { to: '/admin/companies', label: 'Компании' },
    { to: '/admin/users', label: 'Пользователи' },
    { to: '/crm/listings', label: 'CRM / Лоты' },
    { to: '/crm/questions', label: 'Вопросы' },
    { to: '/crm/pipeline', label: 'Pipeline' },
    ...common,
  ];
}

export function AppLayout() {
  const { currentUser, currentCompany, favorites, compare, logout } = useApp();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-card">
          <div className="brand-mark">D</div>
          <div>
            <div className="brand-name">DEVLAND</div>
            <div className="brand-subtitle">Codex-ready platform</div>
          </div>
        </div>
        <div className="profile-card">
          <div className="profile-name">{currentUser?.name}</div>
          <div className="profile-company">{currentCompany?.name}</div>
          <div className="profile-role">{ROLE_LABELS[currentUser?.role]}</div>
          <div className="profile-counters">
            {(currentUser?.role === 'investor' || currentUser?.role === 'developer') && <span>Shortlist: {favorites.length}</span>}
            {(currentUser?.role === 'investor' || currentUser?.role === 'developer') && <span>Compare: {compare.length}</span>}
          </div>
        </div>
        <nav className="sidebar-nav">
          {navItems(currentUser?.role).map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => clsx('sidebar-link', isActive && 'sidebar-link-active')}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <button className="btn btn-secondary sidebar-logout" onClick={logout}>Выйти</button>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div>
            <div className="topbar-label">{ROLE_LABELS[currentUser?.role]}</div>
            <div className="topbar-title">{currentCompany?.name || 'DEVLAND'}</div>
          </div>
        </header>
        <div className="page-content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
