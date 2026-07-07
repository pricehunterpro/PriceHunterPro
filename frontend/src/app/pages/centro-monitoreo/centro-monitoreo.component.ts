import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { DealsStateService } from '../../services/deals-state.service';

interface Summary {
  scrapersActivos: number; scrapersConError: number;
  procesosEjecutando: number; procesosFallidos: number;
  ultimaSincronizacion: string | null; productosHoy: number;
  scrapingActivo: boolean;
}
interface Scraper {
  id: string; store: string; status: string; lastSync: string;
  duracion: string; productos: number; enStock: number; errores: number;
}
interface Task {
  id: string; fullId: string; tipo: string; status: string;
  inicio: string; duracion: string; resultado: string | null; error: string | null;
}
interface Log {
  fecha: string; modulo: string; tipo: string; mensaje: string; severidad: string;
}
interface Sync {
  store: string; ultimaSync: string; proximaSync: string; frecuencia: string; status: string;
}

@Component({
  selector: 'app-centro-monitoreo',
  templateUrl: './centro-monitoreo.component.html',
  styleUrls: ['./centro-monitoreo.component.css'],
  standalone: true,
  imports: [CommonModule],
})
export class CentroMonitoreoComponent implements OnInit, OnDestroy {
  private http = inject(HttpClient);
  protected s  = inject(DealsStateService);

  summary:  Summary  = { scrapersActivos:0, scrapersConError:0, procesosEjecutando:0, procesosFallidos:0, ultimaSincronizacion:null, productosHoy:0, scrapingActivo:false };
  scrapers: Scraper[] = [];
  tasks:    Task[]    = [];
  logs:     Log[]     = [];
  syncs:    Sync[]    = [];

  loading = true;
  private _timer: any;

  ngOnInit(): void { this.loadAll(); this._timer = setInterval(() => this.loadAll(), 30000); }
  ngOnDestroy(): void { clearInterval(this._timer); }

  loadAll(): void {
    this.http.get<Summary>('/api/v1/monitoring/summary').subscribe({ next: r => { this.summary = r; this.loading = false; }, error: () => { this.loading = false; } });
    this.http.get<Scraper[]>('/api/v1/monitoring/scrapers').subscribe({ next: r => this.scrapers = r, error: () => {} });
    this.http.get<Task[]>('/api/v1/monitoring/tasks').subscribe({ next: r => this.tasks = r, error: () => {} });
    this.http.get<Log[]>('/api/v1/monitoring/logs').subscribe({ next: r => this.logs = r, error: () => {} });
    this.http.get<Sync[]>('/api/v1/monitoring/syncs').subscribe({ next: r => this.syncs = r, error: () => {} });
  }

  runNow(scraperId: string): void {
    this.http.post(`/api/v1/monitoring/scrapers/${scraperId}/run`, {}).subscribe({
      next: () => { setTimeout(() => this.loadAll(), 1000); },
      error: () => {},
    });
  }

  statusClass(status: string): string {
    const m: Record<string, string> = {
      'Activo': 'status-active', 'Ejecutando': 'status-running',
      'Finalizado': 'status-done', 'Pausado': 'status-paused',
      'Error': 'status-error', 'Completado': 'status-done',
      'Fallido': 'status-error', 'Pendiente': 'status-paused',
      'Reintentando': 'status-running',
    };
    return m[status] ?? 'status-paused';
  }

  severityClass(sev: string): string {
    const m: Record<string, string> = {
      'info': 'sev-info', 'warning': 'sev-warning',
      'error': 'sev-error', 'critical': 'sev-critical',
    };
    return m[sev] ?? 'sev-info';
  }

  formatSync(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const min = Math.floor((Date.now() - d.getTime()) / 60000);
    if (min < 1)  return 'hace <1 min';
    if (min < 60) return `hace ${min} min`;
    return `hace ${Math.floor(min/60)}h`;
  }
}
