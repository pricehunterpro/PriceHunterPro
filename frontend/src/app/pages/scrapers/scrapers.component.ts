import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface ScraperCfg {
  frecuencia: string; timeout: number; max_reintentos: number; delay_paginas: number;
  max_paginas: number; user_agent: string; proxy: string; headless: boolean; debug: boolean;
}
interface Scraper {
  id: string; store_name: string; scraper_name: string; scraper_type: string; base_url: string;
  method: string; status: string; schedule: string; last_execution: string | null; next_execution: string | null;
  average_time: number; max_time: number; min_time: number;
  total_products: number; new_products: number; updated_products: number; errors: number;
  consecutive_failures: number; configuration_json: ScraperCfg; created_at: string; updated_at: string;
}
interface Kpis {
  registrados: number; activos: number; detenidos: number; conError: number;
  productosHoy: number; tiempoPromedio: number; ultimaSincronizacion: string | null;
}
interface RunHist { fecha: string; duracion: number | null; productos: number; errores: number; estado: string; }

@Component({
  selector: 'app-scrapers',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './scrapers.component.html',
  styleUrls: ['./scrapers.component.css'],
})
export class ScrapersComponent implements OnInit, OnDestroy {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/scrapers';

  loading = false;
  items: Scraper[] = [];
  kpis: Kpis | null = null;
  types: string[] = [];
  schedules: string[] = [];

  detail: Scraper | null = null;
  detailTab: 'info' | 'stats' | 'history' | 'config' = 'info';
  history: RunHist[] = [];
  cfgForm: Partial<ScraperCfg & { schedule: string; scraper_type: string }> = {};

  toast = '';
  private toastTimer: any = null;
  private poll: any = null;

  ngOnInit(): void { this.load(); this.startPoll(); }
  ngOnDestroy(): void { clearInterval(this.poll); clearTimeout(this.toastTimer); }

  load(): void {
    this.loading = true;
    this.http.get<any>(this.base).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.items ?? []; this.types = r.types ?? []; this.schedules = r.schedules ?? []; },
      error: () => { this.items = []; },
    });
    this.http.get<any>(`${this.base}/stats`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} });
  }
  private startPoll(): void {
    this.poll = setInterval(() => {
      if (this.items.some(s => s.status === 'Ejecutando')) this.load();
    }, 5000);
  }

  // ── Acciones ──
  private act(path: string, ok: string): void {
    this.http.post(`${this.base}/${path}`, {}).subscribe({
      next: () => { this.showToast(ok); this.load(); },
      error: e => this.showToast(e?.error?.detail || 'Error'),
    });
  }
  run(s: Scraper): void { this.act(`run/${s.id}`, `Ejecutando ${s.store_name}…`); }
  pause(s: Scraper): void { this.act(`pause/${s.id}`, `${s.store_name} pausado`); }
  resume(s: Scraper): void { this.act(`resume/${s.id}`, `${s.store_name} reanudado`); }
  retry(s: Scraper): void { this.act(`retry/${s.id}`, `Reintentando ${s.store_name}…`); }

  // ── Detalle ──
  openDetail(s: Scraper, tab: 'info' | 'stats' | 'history' | 'config' = 'info'): void {
    this.detail = s; this.detailTab = tab;
    this.cfgForm = { ...s.configuration_json, schedule: s.schedule, scraper_type: s.scraper_type };
    this.loadHistory(s.id);
  }
  closeDetail(): void { this.detail = null; }
  loadHistory(id: string): void {
    this.http.get<any>(`${this.base}/history/${id}`).subscribe({ next: r => this.history = r.items ?? [], error: () => this.history = [] });
  }
  saveConfig(): void {
    if (!this.detail) return;
    this.http.put<any>(`${this.base}/config/${this.detail.id}`, this.cfgForm).subscribe({
      next: r => { this.showToast('Configuración guardada'); this.detail = r.item; this.load(); },
      error: () => this.showToast('Error al guardar'),
    });
  }

  private showToast(msg: string): void {
    this.toast = msg; clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast = '', 2600);
  }

  // ── Helpers ──
  statusClass(s: string): string {
    const m: Record<string, string> = {
      'Activo': 'st-activo', 'Ejecutando': 'st-run', 'Pausado': 'st-pause', 'Error': 'st-error', 'Deshabilitado': 'st-disabled',
    };
    return m[s] ?? 'st-activo';
  }
  typeClass(t: string): string { return 'ty-' + t.toLowerCase(); }
  storeBadge(id: string): string {
    const m: Record<string, string> = {
      falabella: 'store-falabella', ripley: 'store-ripley', plazavea: 'store-plazavea',
      oechsle: 'store-oechsle', tottus: 'store-tottus', estilos: 'store-estilos',
      sodimac: 'store-sodimac', mercadolibre: 'store-mercadolibre',
      shopstar: 'store-shopstar',
    };
    return m[id] ?? 'store-default';
  }
  get maxProducts(): number { return Math.max(1, ...this.items.map(s => s.total_products)); }
  pct(v: number): number { return Math.round((v / this.maxProducts) * 100); }
}
