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

export const routes: Routes = [
  {
    path: '',
    component: AppLayoutComponent,
    children: [
      { path: '',                           redirectTo: 'oportunidades', pathMatch: 'full' },
      { path: 'oportunidades',              component: OportunidadesComponent },
      { path: 'alertas',                    component: AlertasComponent },
      { path: 'gangas',                     component: GangasComponent },
      { path: 'motor-ia',                   component: MotorIaComponent },
      { path: 'automatizacion/monitoreo',   component: CentroMonitoreoComponent },
      { path: 'marketing/tiktok-factory',   component: TiktokFactoryComponent },
      { path: 'marketing/supervision',      component: SupervisionComponent },
      { path: 'marketing/publicador-ia',    component: PublicadorComponent },
      { path: '**',                         component: ComingSoonComponent },
    ],
  },
];
