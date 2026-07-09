import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';

interface SysLog {
  id: string; level: string; module: string; log_type: string; message: string;
  stack_trace: string; payload_json: any; related_process_id: string | null;
  related_scraper_id: string | null; user_id: string; ip_address: string;
  status: string; created_at: string; updated_at: string;
}
interface Kpis {
  total: number; criticos: number; warnings: number; errores24h: number;
  moduloConMasErrores: string; ultimoError: string;
}

@Component({
  selector: 'app-logs',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './logs.component.html',
  styleUrls: ['./logs.component.css'],
})
export class LogsComponent implements OnInit, OnDestroy {
  private http = inject(HttpClient);
  private router = inject(Router);
  private readonly base = '/api/v1/logs';

  loading = false;
  items: SysLog[] = [];
  kpis: Kpis | null = null;
  niveles: string[] = []; tipos: string[] = []; estados: string[] = []; modulos: string[] = [];

  fLevel = ''; fModule = ''; fType = ''; fStatus = ''; q = '';

  detail: SysLog | null = null;
  showStack = false;
  toast = '';
  private toastTimer: any = null;
  private poll: any = null;

  ngOnInit(): void { this.load(); this.poll = setInterval(() => this.loadStats(), 15000); }
  ngOnDestroy(): void { clearInterval(this.poll); clearTimeout(this.toastTimer); }

  private params(): Record<string, string> {
    const p: Record<string, string> = {};
    if (this.fLevel) p['level'] = this.fLevel;
    if (this.fModule) p['module'] = this.fModule;
    if (this.fType) p['log_type'] = this.fType;
    if (this.fStatus) p['status'] = this.fStatus;
    if (this.q) p['q'] = this.q;
    return p;
  }
  load(): void {
    this.loading = true;
    this.http.get<any>(this.base, { params: this.params() }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.items ?? []; this.niveles = r.niveles ?? []; this.tipos = r.tipos ?? []; this.estados = r.estados ?? []; this.modulos = r.modulos ?? []; },
      error: () => { this.items = []; },
    });
    this.loadStats();
  }
  loadStats(): void { this.http.get<any>(`${this.base}/stats`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} }); }
  clearFilters(): void { this.fLevel = this.fModule = this.fType = this.fStatus = this.q = ''; this.load(); }

  // ── Acciones ──
  setStatus(l: SysLog, status: string): void {
    this.http.put<any>(`${this.base}/${l.id}/status`, { status }).subscribe({
      next: r => { this.showToast(`Marcado como ${status}`); if (this.detail?.id === l.id) this.detail = r.item; this.load(); },
      error: () => this.showToast('Error'),
    });
  }
  copyError(l: SysLog): void {
    const txt = `[${l.level}] ${l.module}/${l.log_type}\n${l.message}\n${l.stack_trace || ''}`;
    navigator.clipboard?.writeText(txt).then(() => this.showToast('Error copiado al portapapeles'), () => this.showToast('No se pudo copiar'));
  }
  retryRelated(l: SysLog, ev?: Event): void {
    ev?.stopPropagation();
    this.http.post<any>(`${this.base}/${l.id}/retry-related`, {}).subscribe({
      next: r => this.showToast(`Reintentando ${r.kind === 'scraper' ? 'scraper' : 'proceso'}: ${r.id}`),
      error: e => this.showToast(e?.error?.detail || 'Sin relación para reintentar'),
    });
  }
  download(): void {
    const qs = new URLSearchParams(this.params()).toString();
    window.open(`${this.base}/export${qs ? '?' + qs : ''}`, '_blank');
  }
  openScraper(): void { this.router.navigate(['/automatizacion/scrapers']); }
  openProcess(): void { this.router.navigate(['/automatizacion/procesos']); }

  openDetail(l: SysLog): void { this.detail = l; this.showStack = false; }
  closeDetail(): void { this.detail = null; }

  private showToast(msg: string): void { this.toast = msg; clearTimeout(this.toastTimer); this.toastTimer = setTimeout(() => this.toast = '', 2500); }

  levelClass(l: string): string { return 'lv-' + l.toLowerCase(); }
  statusClass(s: string): string {
    const m: Record<string, string> = { Nuevo: 'ss-new', Revisado: 'ss-review', Resuelto: 'ss-ok', Ignorado: 'ss-ign' };
    return m[s] ?? 'ss-new';
  }
  json(o: any): string { return o ? JSON.stringify(o, null, 2) : '—'; }
  short(id: string): string { return id ? id.slice(0, 8) : ''; }
}
