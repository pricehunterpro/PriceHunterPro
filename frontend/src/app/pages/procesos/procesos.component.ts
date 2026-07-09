import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface ProcessTask {
  id: string; task_id: string; process_type: string; module: string; status: string; priority: string;
  payload_json: any; result_json: any; error_message: string; worker_name: string | null;
  started_at: string | null; finished_at: string | null; duration_seconds: number | null;
  retry_count: number; max_retries: number; logs: string[]; state_history: { estado: string; at: string }[];
  created_at: string; updated_at: string; next_retry: string | null;
}
interface Kpis {
  totales: number; enEjecucion: number; pendientes: number; completados: number;
  fallidos: number; tiempoPromedio: number; colaActiva: number;
}

@Component({
  selector: 'app-procesos',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './procesos.component.html',
  styleUrls: ['./procesos.component.css'],
})
export class ProcesosComponent implements OnInit, OnDestroy {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/processes';

  loading = false;
  items: ProcessTask[] = [];
  kpis: Kpis | null = null;
  tipos: string[] = [];
  estados: string[] = [];
  workers: string[] = [];
  prioridades: string[] = [];
  modules: string[] = [];

  fEstado = ''; fTipo = ''; fModule = ''; fWorker = ''; fPrioridad = '';

  detail: ProcessTask | null = null;
  detailTab: 'info' | 'data' | 'log' | 'history' = 'info';

  toast = '';
  private toastTimer: any = null;
  private poll: any = null;

  ngOnInit(): void { this.load(); this.poll = setInterval(() => { if (this.items.some(p => p.status === 'Ejecutando' || p.status === 'Reintentando')) this.load(); }, 6000); }
  ngOnDestroy(): void { clearInterval(this.poll); clearTimeout(this.toastTimer); }

  load(): void {
    this.loading = true;
    const params: Record<string, string> = {};
    if (this.fEstado) params['estado'] = this.fEstado;
    if (this.fTipo) params['tipo'] = this.fTipo;
    if (this.fModule) params['module'] = this.fModule;
    if (this.fWorker) params['worker'] = this.fWorker;
    if (this.fPrioridad) params['prioridad'] = this.fPrioridad;
    this.http.get<any>(this.base, { params }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.items = r.items ?? [];
        this.tipos = r.tipos ?? []; this.estados = r.estados ?? []; this.workers = r.workers ?? [];
        this.prioridades = r.prioridades ?? []; this.modules = r.modules ?? [];
      },
      error: () => { this.items = []; },
    });
    this.http.get<any>(`${this.base}/stats`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} });
  }
  clearFilters(): void { this.fEstado = this.fTipo = this.fModule = this.fWorker = this.fPrioridad = ''; this.load(); }

  private act(pid: string, action: string, ok: string): void {
    this.http.post<any>(`${this.base}/${pid}/${action}`, {}).subscribe({
      next: r => { this.showToast(ok); if (this.detail?.id === pid && r.item) this.detail = r.item; this.load(); },
      error: e => this.showToast(e?.error?.detail || 'Error'),
    });
  }
  retry(p: ProcessTask): void { this.act(p.id, 'retry', 'Reintentando proceso'); }
  cancel(p: ProcessTask): void { this.act(p.id, 'cancel', 'Proceso cancelado'); }
  pause(p: ProcessTask): void { this.act(p.id, 'pause', 'Proceso pausado'); }
  runAgain(p: ProcessTask): void { this.act(p.id, 'run-again', 'Proceso reencolado'); }

  openDetail(p: ProcessTask, tab: 'info' | 'data' | 'log' | 'history' = 'info'): void { this.detail = p; this.detailTab = tab; }
  closeDetail(): void { this.detail = null; }

  private showToast(msg: string): void { this.toast = msg; clearTimeout(this.toastTimer); this.toastTimer = setTimeout(() => this.toast = '', 2500); }

  statusClass(s: string): string {
    const m: Record<string, string> = {
      Pendiente: 'st-pend', Ejecutando: 'st-run', Completado: 'st-done', Fallido: 'st-fail', Cancelado: 'st-cancel', Reintentando: 'st-retry',
    };
    return m[s] ?? 'st-pend';
  }
  prioClass(p: string): string { return 'pr-' + p.toLowerCase(); }
  json(o: any): string { return o ? JSON.stringify(o, null, 2) : '—'; }
  logClass(line: string): string {
    if (line.includes('[ERROR]')) return 'lg-err';
    if (line.includes('[WARN]')) return 'lg-warn';
    return 'lg-info';
  }
  shortId(id: string): string { return id ? id.slice(0, 8) : ''; }
}
