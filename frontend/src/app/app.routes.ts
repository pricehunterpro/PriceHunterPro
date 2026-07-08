import { Routes } from '@angular/router';
import { AppLayoutComponent } from './layout/app-layout.component';
import { OportunidadesComponent } from './pages/oportunidades/oportunidades.component';
import { AlertasComponent } from './pages/alertas/alertas.component';
import { GangasComponent } from './pages/gangas/gangas.component';
import { MotorIaComponent } from './pages/motor-ia/motor-ia.component';
import { ComingSoonComponent } from './pages/coming-soon/coming-soon.component';
import { CentroMonitoreoComponent } from './pages/centro-monitoreo/centro-monitoreo.component';
import { TiktokFactoryComponent } from './pages/tiktok-factory/tiktok-factory.component';
import { SupervisionComponent } from './pages/supervision/supervision.component';
import { PublicadorComponent } from './pages/publicador/publicador.component';
import { LoginComponent } from './pages/login/login.component';
import { authGuard, adminGuard } from './guards/auth.guard';

export const routes: Routes = [
  { path: 'login', component: LoginComponent },
  {
    path: '',
    component: AppLayoutComponent,
    canActivate: [authGuard],
    children: [
      { path: '', redirectTo: 'oportunidades', pathMatch: 'full' },

      // ── Acceso viewer + admin ──
      { path: 'oportunidades', component: OportunidadesComponent },
      { path: 'alertas',       component: AlertasComponent },
      { path: 'gangas',        component: GangasComponent },

      // ── Solo admin ──
      { path: 'motor-ia',                    component: MotorIaComponent,         canActivate: [adminGuard] },
      { path: 'automatizacion/monitoreo',    component: CentroMonitoreoComponent, canActivate: [adminGuard] },
      { path: 'marketing/tiktok-factory',    component: TiktokFactoryComponent,   canActivate: [adminGuard] },
      { path: 'marketing/supervision',       component: SupervisionComponent,     canActivate: [adminGuard] },
      { path: 'marketing/publicador-ia',     component: PublicadorComponent,      canActivate: [adminGuard] },

      { path: '**', component: ComingSoonComponent },
    ],
  },
];
