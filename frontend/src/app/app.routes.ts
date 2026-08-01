import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'user', pathMatch: 'full' },
  {
    path: 'user',
    title: 'Ask — RAG Assistant',
    loadComponent: () => import('./user/user').then((m) => m.User),
  },
  {
    path: 'admin',
    title: 'Admin — RAG Assistant',
    loadComponent: () => import('./admin/admin').then((m) => m.Admin),
  },
  { path: '**', redirectTo: 'user' },
];
