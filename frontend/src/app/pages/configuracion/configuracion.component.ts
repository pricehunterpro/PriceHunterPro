import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

import {
  CategoryMeta,
  ColorPickerComponent,
  ConfigurationTableComponent,
  Integration,
  IntegrationCardComponent,
  SettingItem,
  SettingsCardComponent,
  SettingsSectionComponent,
  SettingsSidebarComponent,
  SystemStatusCardComponent,
  ToggleSwitchComponent,
} from './components/settings-ui';

interface Kpis {
  configuracionesActivas: number;
  configuracionesTotales: number;
  integracionesConectadas: number;
  integracionesTotales: number;
  scrapersActivos: number;
  scrapersTotales: number;
  canalesActivos: number;
  canalesTotales: number;
  estadoSistema: string;
}

interface SystemStatus {
  version: string;
  ambiente: string;
  ambienteReal: string;
  memoria: { usadoMb: number; totalMb: number; porcentaje: number; fuente: string };
  cpu: { porcentaje: number; load1: number; load5: number; load15: number; nucleos: number };
  disco: { usadoGb: number; totalGb: number; porcentaje: number };
  uptime: { segundos: number; texto: string; procesoTexto: string };
  python: string;
  baseDatos: {
    conectado: boolean; motor: string; host: string; tamano: string; tablas: number;
    filas: Record<string, number>; ultimaMigracion: string; ultimoBackup: string | null;
    error: string; version?: string;
  };
  kpis: Kpis;
}

interface AuditRow {
  label: string; category: string; key: string;
  old_value: string; new_value: string; updated_by: string; created_at: string;
}

const API = '/api/v1/settings';

@Component({
  selector: 'app-configuracion',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    SettingsSidebarComponent, SettingsSectionComponent, SettingsCardComponent,
    ColorPickerComponent, ToggleSwitchComponent, ConfigurationTableComponent,
    SystemStatusCardComponent, IntegrationCardComponent,
  ],
  templateUrl: './configuracion.component.html',
  styleUrls: ['./configuracion.component.css'],
})
export class ConfiguracionComponent implements OnInit {
  private http = inject(HttpClient);

  categories: CategoryMeta[] = [];
  sections: Record<string, SettingItem[]> = {};
  kpis: Kpis | null = null;
  ambiente = '';
  active = 'general';

  status: SystemStatus | null = null;
  integraciones: Integration[] = [];
  audit: AuditRow[] = [];

  loading = false;
  saving = false;
  error = '';
  toast = '';
  toastError = false;
  busyIntegration = '';
  private toastTimer: any = null;

  /** Cambios pendientes: "categoria.clave" → valor nuevo. */
  private pendientes = new Map<string, any>();

  ngOnInit(): void {
    this.load();
  }

  // ── Carga ──
  load(): void {
    this.loading = true;
    this.error = '';
    this.http.get<{ ambiente: string; categorias: CategoryMeta[]; secciones: Record<string, SettingItem[]>; kpis: Kpis }>(API)
      .pipe(finalize(() => (this.loading = false)))
      .subscribe({
        next: r => {
          this.ambiente = r.ambiente;
          this.categories = r.categorias ?? [];
          this.sections = r.secciones ?? {};
          this.kpis = r.kpis ?? null;
          this.pendientes.clear();
          this.loadSideData();
        },
        error: () => { this.error = 'No se pudo cargar la configuración.'; },
      });
  }

  private loadSideData(): void {
    this.http.get<SystemStatus>(`${API}/system-status`).subscribe({
      next: r => (this.status = r),
      error: () => (this.status = null),
    });
    this.http.get<{ items: Integration[] }>(`${API}/integrations`).subscribe({
      next: r => (this.integraciones = r.items ?? []),
      error: () => (this.integraciones = []),
    });
    this.loadAudit();
  }

  private loadAudit(): void {
    this.http.get<{ items: AuditRow[] }>(`${API}/audit?limit=25`).subscribe({
      next: r => (this.audit = r.items ?? []),
      error: () => (this.audit = []),
    });
  }

  // ── Navegación de pestañas ──
  selectCategory(id: string): void { this.active = id; }

  get activeMeta(): CategoryMeta | undefined {
    return this.categories.find(c => c.id === this.active);
  }

  get activeItems(): SettingItem[] { return this.sections[this.active] ?? []; }

  // ── Cambios pendientes ──
  onValueChange(item: SettingItem, value: any): void {
    this.pendientes.set(`${item.category}.${item.key}`, value);
  }

  isDirty(item: SettingItem): boolean {
    return this.pendientes.has(`${item.category}.${item.key}`);
  }

  get dirtyCount(): number { return this.pendientes.size; }

  get dirtyByCategory(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const clave of this.pendientes.keys()) {
      const cat = clave.split('.')[0];
      out[cat] = (out[cat] ?? 0) + 1;
    }
    return out;
  }

  // ── Guardar / descartar / reset ──
  save(): void {
    if (!this.pendientes.size || this.saving) return;
    this.saving = true;
    const changes = [...this.pendientes.entries()].map(([clave, value]) => {
      const idx = clave.indexOf('.');
      return { category: clave.slice(0, idx), key: clave.slice(idx + 1), value };
    });

    this.http.put<{ aplicados: number }>(API, { changes, updated_by: this.currentUser() })
      .pipe(finalize(() => (this.saving = false)))
      .subscribe({
        next: r => {
          this.showToast(
            r.aplicados
              ? `${r.aplicados} ajuste${r.aplicados === 1 ? '' : 's'} guardado${r.aplicados === 1 ? '' : 's'}`
              : 'No había cambios reales que guardar',
          );
          this.load();
        },
        error: err => this.showToast(err?.error?.detail ?? 'No se pudo guardar', true),
      });
  }

  discard(): void {
    if (!this.pendientes.size) return;
    this.pendientes.clear();
    this.load();
    this.showToast('Cambios descartados');
  }

  resetCategory(): void {
    const meta = this.activeMeta;
    if (!meta) return;
    this.saving = true;
    this.http.post<{ restaurados: number }>(`${API}/reset`, { category: meta.id, updated_by: this.currentUser() })
      .pipe(finalize(() => (this.saving = false)))
      .subscribe({
        next: r => {
          this.showToast(`${meta.label}: ${r.restaurados} ajuste(s) restaurado(s) a su valor por defecto`);
          this.load();
        },
        error: err => this.showToast(err?.error?.detail ?? 'No se pudo restaurar', true),
      });
  }

  clearCache(): void {
    this.http.post<{ limpiadas: string[] }>(`${API}/clear-cache`, {}).subscribe({
      next: r => this.showToast(`Caché limpiada: ${r.limpiadas.join(', ')}`),
      error: () => this.showToast('No se pudo limpiar la caché', true),
    });
  }

  // ── Integraciones (las de canales las atiende el módulo Canales) ──
  onIntegrationAction(item: Integration, accion: 'connect' | 'disconnect' | 'test' | 'renew'): void {
    if (item.gestionadoPor !== 'channels' || !item.endpointBase) {
      this.showToast(`${item.nombre} se configura en los campos de esta pestaña`, true);
      return;
    }
    if (accion === 'connect' || accion === 'renew') {
      this.showToast(`Para ${accion === 'connect' ? 'conectar' : 'renovar el token de'} ${item.nombre} usa Administración → Canales`, true);
      return;
    }
    const path = accion === 'disconnect' ? 'disconnect' : 'test';
    this.busyIntegration = item.id;
    this.http.post<{ ok?: boolean; mensaje?: string }>(`${item.endpointBase}/${path}`, {})
      .pipe(finalize(() => (this.busyIntegration = '')))
      .subscribe({
        next: r => {
          this.showToast(r?.mensaje ?? `${item.nombre}: acción completada`);
          this.loadSideData();
        },
        error: err => this.showToast(err?.error?.detail ?? `${item.nombre}: la acción falló`, true),
      });
  }

  // ── Base de datos ──
  runMigrations(): void {
    this.showToast('Las migraciones se ejecutan al arrancar el backend (alembic upgrade head)', true);
  }
  createBackup(): void {
    this.showToast('Backup: pendiente de integrar con Supabase', true);
  }

  // ── Utilidades ──
  private currentUser(): string {
    try {
      const raw = localStorage.getItem('ph_user');
      if (raw) {
        const u = JSON.parse(raw);
        return u?.email || u?.full_name || 'admin';
      }
    } catch { /* sin sesión guardada */ }
    return 'admin';
  }

  private showToast(msg: string, isError = false): void {
    this.toast = msg;
    this.toastError = isError;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => (this.toast = ''), 4200);
  }

  estadoClass(estado: string): string {
    if (estado === 'Operativo') return 'ok';
    if (estado === 'Degradado') return 'warn';
    return 'crit';
  }

  filasBD(): { tabla: string; filas: number }[] {
    const f = this.status?.baseDatos?.filas ?? {};
    return Object.entries(f).map(([tabla, filas]) => ({ tabla, filas }));
  }
}
