export const STAGES = ['new', 'qualified', 'nda', 'review', 'offer', 'dd', 'won', 'lost'];

export const STAGE_LABELS = {
  new: 'Новый',
  qualified: 'Квалификация',
  nda: 'NDA',
  review: 'Review',
  offer: 'Offer',
  dd: 'DD',
  won: 'Won',
  lost: 'Lost',
};

export const ROLE_LABELS = {
  investor: 'Инвестор',
  developer: 'Девелопер',
  seller: 'Продавец',
  broker: 'Брокер',
  admin: 'Администратор',
};

export const seedData = {
  companies: [
    { id: 'c-devland', name: 'DEVLAND', type: 'platform', city: 'Москва', website: 'devland.local', note: 'Оператор платформы', isVerified: true },
    { id: 'c-capital', name: 'Capital Development Partners', type: 'investor', city: 'Москва', website: 'capital.local', note: 'Инвестор / девелопер', isVerified: true },
    { id: 'c-topland', name: 'Topland Advisory', type: 'broker', city: 'Москва', website: 'topland.local', note: 'Брокер и консультант', isVerified: true },
    { id: 'c-industrial', name: 'Industrial Node', type: 'owner', city: 'Подольск', website: 'node.local', note: 'Собственник индустриальных площадок', isVerified: false }
  ],
  users: [
    { id: 'u-investor', name: 'Александр', email: 'investor@devland.ru', password: '123456', role: 'investor', companyId: 'c-capital', city: 'Москва', phone: '+7 900 000 00 01', isActive: true },
    { id: 'u-seller', name: 'Мария', email: 'seller@devland.ru', password: '123456', role: 'seller', companyId: 'c-topland', city: 'Москва', phone: '+7 900 000 00 02', isActive: true },
    { id: 'u-admin', name: 'Администратор', email: 'admin@devland.ru', password: '123456', role: 'admin', companyId: 'c-devland', city: 'Москва', phone: '+7 900 000 00 03', isActive: true },
    { id: 'u-owner-1', name: 'Игорь Соколов', email: 'owner@industrial.local', password: '123456', role: 'broker', companyId: 'c-industrial', city: 'Подольск', phone: '+7 900 000 00 04', isActive: true }
  ],
  listings: [
    {
      id: 'l-1',
      ownerId: 'u-seller',
      companyId: 'c-topland',
      title: 'ЗУ под жилую застройку, Нагатинская пойма',
      type: 'ЗУ',
      strategy: 'МЖС',
      region: 'Москва',
      district: 'ЮАО',
      address: 'Москва, Нагатинская пойма',
      area: '2.8',
      price: '1450',
      priceType: 'Фиксированная цена',
      format: 'Exclusive',
      verified: true,
      score: 84,
      teaser: 'Участок с высоким потенциалом mixed-use / МЖС, рядом магистрали и крупные жилые кластеры.',
      description: 'Площадка подходит под жилую или mixed-use застройку. В базовом пакете доступны teaser, правоустанавливающие, градостроительные и технические документы.',
      tags: ['ГПЗУ', 'Метро 12 мин', 'Best use'],
      risk: 'Средний',
      privacy: 'NDA',
      status: 'published',
      createdAt: '2026-04-18',
      image: 'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?q=80&w=1600&auto=format&fit=crop',
      documents: [
        { id: 'd-1', name: 'Teaser.pdf', category: 'Marketing', access: 'public', size: '2.4 MB' },
        { id: 'd-2', name: 'Выписка ЕГРН.pdf', category: 'Legal', access: 'nda', size: '1.1 MB' },
        { id: 'd-3', name: 'ГПЗУ.pdf', category: 'Urban Planning', access: 'nda', size: '6.3 MB' },
        { id: 'd-4', name: 'Презентация проекта.pdf', category: 'Marketing', access: 'approved', size: '12.5 MB' }
      ],
      summary: 'Сильная городская локация, высокий интерес девелоперов, понятный сценарий best use.'
    },
    {
      id: 'l-2',
      ownerId: 'u-seller',
      companyId: 'c-topland',
      title: 'Имущественный комплекс под редевелопмент, Бауманская',
      type: 'Редевелопмент',
      strategy: 'Mixed-use',
      region: 'Москва',
      district: 'ЦАО',
      address: 'Москва, район Бауманская',
      area: '1.2',
      price: '980',
      priceType: 'Индикатив',
      format: 'Private',
      verified: true,
      score: 89,
      teaser: 'Бывшая производственная площадка с потенциалом офисно-жилой реконцепции.',
      description: 'Актив с сильной локацией, приватным режимом показа и расширенным документным пакетом.',
      tags: ['Off-market', 'Документы', 'Техобследование'],
      risk: 'Выше среднего',
      privacy: 'Request',
      status: 'published',
      createdAt: '2026-04-17',
      image: 'https://images.unsplash.com/photo-1460317442991-0ec209397118?q=80&w=1600&auto=format&fit=crop',
      documents: [
        { id: 'd-5', name: 'Teaser.pdf', category: 'Marketing', access: 'public', size: '2.8 MB' },
        { id: 'd-6', name: 'Техобследование.pdf', category: 'Technical', access: 'approved', size: '8.1 MB' },
        { id: 'd-7', name: 'Структура владения.pdf', category: 'Legal', access: 'nda', size: '1.4 MB' }
      ],
      summary: 'Сильный потенциал реконцепции, но более сложный юридический контур.'
    },
    {
      id: 'l-3',
      ownerId: 'u-owner-1',
      companyId: 'c-industrial',
      title: 'ЗУ под light industrial, Подольск',
      type: 'ЗУ',
      strategy: 'Industrial',
      region: 'МО',
      district: 'Подольск',
      address: 'МО, Подольск',
      area: '6.5',
      price: '620',
      priceType: 'Фиксированная цена',
      format: 'Public',
      verified: true,
      score: 78,
      teaser: 'Площадка под складской или производственный кластер, удобный выезд на ЦКАД.',
      description: 'Участок для индустриального использования с хорошей транспортной связностью.',
      tags: ['Инженерия рядом', 'Трасса', 'Склад'],
      risk: 'Низкий',
      privacy: 'Public',
      status: 'published',
      createdAt: '2026-04-14',
      image: 'https://images.unsplash.com/photo-1511818966892-d7d671e672a2?q=80&w=1600&auto=format&fit=crop',
      documents: [
        { id: 'd-8', name: 'Teaser.pdf', category: 'Marketing', access: 'public', size: '2.1 MB' },
        { id: 'd-9', name: 'Схема коммуникаций.pdf', category: 'Technical', access: 'public', size: '4.2 MB' }
      ],
      summary: 'Быстрый и понятный актив для industrial-стратегий с низким барьером входа.'
    }
  ],
  accessRequests: [
    { id: 'ar-1', listingId: 'l-1', requesterId: 'u-investor', ownerId: 'u-seller', message: 'Интересует полный пакет документов для инвесткома.', status: 'approved', ndaAccepted: true, createdAt: '2026-04-20 10:30' }
  ],
  offers: [
    { id: 'of-1', listingId: 'l-1', userId: 'u-investor', amount: '1380', comment: 'Готовы обсуждать после проверки ограничений и ГПЗУ.', status: 'received', createdAt: '2026-04-20 11:10' }
  ],
  questions: [
    { id: 'q-1', listingId: 'l-1', userId: 'u-investor', ownerId: 'u-seller', question: 'Есть ли ограничения по охранным зонам и сервитутам?', answer: 'В полном пакете есть выписка и градостроительные материалы.', createdAt: '2026-04-20 11:45' }
  ],
  deals: [
    { id: 'deal-1', listingId: 'l-1', companyId: 'c-capital', ownerId: 'u-seller', title: 'Нагатинская пойма / Capital Development Partners', stage: 'dd', amount: '1380', nextStep: 'Финализировать замечания к ГПЗУ', updatedAt: '2026-04-21 10:15' },
    { id: 'deal-2', listingId: 'l-2', companyId: 'c-capital', ownerId: 'u-seller', title: 'Бауманская / Capital Development Partners', stage: 'review', amount: '980', nextStep: 'Открыть техобследование и ownership structure', updatedAt: '2026-04-21 09:00' },
    { id: 'deal-3', listingId: 'l-3', companyId: 'c-capital', ownerId: 'u-owner-1', title: 'Подольск / Capital Development Partners', stage: 'qualified', amount: '620', nextStep: 'Подготовить инвестиционное резюме', updatedAt: '2026-04-21 08:40' }
  ],
  favoritesByUser: { 'u-investor': ['l-1', 'l-2'] },
  compareByUser: { 'u-investor': ['l-1', 'l-3'] },
  auditLogs: [
    { id: 'log-1', action: 'LOGIN', actor: 'u-investor', entity: 'auth', createdAt: '2026-04-20 09:00' },
    { id: 'log-2', action: 'REQUEST_ACCESS', actor: 'u-investor', entity: 'l-1', createdAt: '2026-04-20 10:30' }
  ]
};
