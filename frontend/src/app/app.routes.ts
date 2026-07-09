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
import { CalendarioComponent } from './pages/calendario/calendario.component';
import { RankingIaComponent } from './pages/ranking-ia/ranking-ia.component';
import { TendenciasComponent } from './pages/tendencias/tendencias.component';
import { AnalyticsComponent } from './pages/analytics/analytics.component';
import { RentabilidadComponent } from './pages/rentabilidad/rentabilidad.component';
import { PortafolioComponent } from './pages/portafolio/portafolio.component';
import { TopProductosComponent } from './pages/top-productos/top-productos.component';
import { PlantillasComponent } from './pages/plantillas/plantillas.component';
import { ScrapersComponent } from './pages/scrapers/scrapers.component';
import { ProcesosComponent } from './pages/procesos/procesos.component';
import { LogsComponent } from './pages/logs/logs.component';
import { HistorialComponent } from './pages/historial/historial.component';
import { UsuariosComponent } from './pages/usuarios/usuarios.component';
import { TiendasComponent } from './pages/tiendas/tiendas.component';
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
      { path: 'oportunidades/historial', component: HistorialComponent },

      // ── Solo admin ──
      { path: 'motor-ia',                    component: MotorIaComponent,         canActivate: [adminGuard] },
      { path: 'inteligencia-ia/ranking-ia',  component: RankingIaComponent,       canActivate: [adminGuard] },
      { path: 'inteligencia-ia/tendencias',  component: TendenciasComponent,      canActivate: [adminGuard] },
      { path: 'business-intelligence/analytics', component: AnalyticsComponent,   canActivate: [adminGuard] },
      { path: 'business-intelligence/rentabilidad', component: RentabilidadComponent, canActivate: [adminGuard] },
      { path: 'business-intelligence/portafolio', component: PortafolioComponent,   canActivate: [adminGuard] },
      { path: 'business-intelligence/top-productos', component: TopProductosComponent, canActivate: [adminGuard] },
      { path: 'automatizacion/monitoreo',    component: CentroMonitoreoComponent, canActivate: [adminGuard] },
      { path: 'automatizacion/scrapers',     component: ScrapersComponent,        canActivate: [adminGuard] },
      { path: 'automatizacion/procesos',     component: ProcesosComponent,        canActivate: [adminGuard] },
      { path: 'automatizacion/logs',         component: LogsComponent,            canActivate: [adminGuard] },
      { path: 'administracion/usuarios',     component: UsuariosComponent,        canActivate: [adminGuard] },
      { path: 'administracion/tiendas',      component: TiendasComponent,         canActivate: [adminGuard] },
      { path: 'marketing/tiktok-factory',    component: TiktokFactoryComponent,   canActivate: [adminGuard] },
      { path: 'marketing/supervision',       component: SupervisionComponent,     canActivate: [adminGuard] },
      { path: 'marketing/publicador-ia',     component: PublicadorComponent,      canActivate: [adminGuard] },
      { path: 'marketing/plantillas',        component: PlantillasComponent,      canActivate: [adminGuard] },
      { path: 'calendario',                  component: CalendarioComponent,      canActivate: [adminGuard] },

      { path: '**', component: ComingSoonComponent },
    ],
  },
];
