import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface HistRow {
  id: string; name: string; brand: string; category: string; store: string; sku: string; url: string;
  imageUrl: string; inStock: boolean; currentPrice: number; precioMin: number; precioMax: number;
  precioProm: number; cambios: number; ultimoCambio: string | null; variacionPct: number; score: number; esMinimo: boolean;
}
interface Kpis {
  productosConHistorial: number; cambiosRegistrados: number; precioMinHistorico: number;
  precioMaxHistorico: number; variacionPromedio: number; ultimaSincronizacion: string | null;
}
interface Detail {
  id: string; name: string; brand: string; category: string; store: string; sku: string; url: string;
  imageUrl: string; inStock: boolean; score: number;
  stats: { precioMin: number; precioMax: number; precioProm: number; precioActual: number; variacion: number; mayorDescuento: number; diasMonitoreados: number; cambios: number; };
  alertas: { esMinimoHistorico: boolean; subioDePrecio: boolean; bajoDePrecio: boolean; volvioAlMinimo: boolean; };
}
interface Chart { period: string; labels: string[]; precios: number[]; descuentos: number[]; scores: number[]; }
interface TL { fecha: string; precio: number; direccion: string; esMinimo: boolean; }

@Component({
  selector: 'app-historial',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './historial.component.html',
  styleUrls: ['./historial.component.css'],
})
export class HistorialComponent implements OnInit {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/history';

  loading = false;
  items: HistRow[] = [];
  kpis: Kpis | null = null;
  total = 0; page = 1; limit = 50;

  q = ''; fStore = ''; fCategory = ''; fBrand = ''; fMinPrice: number | null = null; fMaxPrice: number | null = null; fMinScore = 0;
  storesList: string[] = []; categoriesList: string[] = []; brandsList: string[] = [];

  // Detalle
  detail: Detail | null = null;
  chart: Chart | null = null;
  timeline: TL[] = [];
  loadingDetail = false;
  chartPeriod = '90d';
  chartMetric: 'precios' | 'descuentos' | 'scores' = 'precios';
  readonly periods = [
    { v: '7d', l: '7d' }, { v: '30d', l: '30d' }, { v: '90d', l: '90d' }, { v: '180d', l: '180d' }, { v: '1y', l: '1 año' },
  ];

  ngOnInit(): void { this.loadFilters(); this.load(); this.loadStats(); }

  private params(): Record<string, string> {
    const p: Record<string, string> = { page: String(this.page), limit: String(this.limit) };
    if (this.q) p['q'] = this.q;
    if (this.fStore) p['store'] = this.fStore;
    if (this.fCategory) p['category'] = this.fCategory;
    if (this.fBrand) p['brand'] = this.fBrand;
    if (this.fMinPrice) p['min_price'] = String(this.fMinPrice);
    if (this.fMaxPrice) p['max_price'] = String(this.fMaxPrice);
    if (this.fMinScore) p['min_score'] = String(this.fMinScore);
    return p;
  }
  load(): void {
    this.loading = true;
    this.http.get<any>(this.base, { params: this.params() }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.items ?? []; this.total = r.total ?? 0; },
      error: () => { this.items = []; },
    });
  }
  loadStats(): void { this.http.get<any>(`${this.base}/stats`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} }); }
  loadFilters(): void {
    this.http.get<any>('/api/v1/ai/trends').subscribe({
      next: r => { this.storesList = r.filters?.stores ?? []; this.categoriesList = r.filters?.categories ?? []; this.brandsList = r.filters?.brands ?? []; },
      error: () => {},
    });
  }
  search(): void { this.page = 1; this.load(); }
  clearFilters(): void { this.q = this.fStore = this.fCategory = this.fBrand = ''; this.fMinPrice = this.fMaxPrice = null; this.fMinScore = 0; this.page = 1; this.load(); }
  get totalPages(): number { return Math.max(1, Math.ceil(this.total / this.limit)); }
  goPage(p: number): void { if (p < 1 || p > this.totalPages) return; this.page = p; this.load(); }

  download(): void {
    const p: Record<string, string> = {};
    if (this.q) p['q'] = this.q;
    if (this.fStore) p['store'] = this.fStore;
    if (this.fCategory) p['category'] = this.fCategory;
    if (this.fBrand) p['brand'] = this.fBrand;
    const qs = new URLSearchParams(p).toString();
    window.open(`${this.base}/export/csv${qs ? '?' + qs : ''}`, '_blank');
  }

  // ── Detalle ──
  open(row: HistRow): void {
    this.loadingDetail = true;
    this.detail = null; this.chart = null; this.timeline = [];
    this.http.get<any>(`${this.base}/${row.id}`).pipe(finalize(() => this.loadingDetail = false)).subscribe({
      next: r => { this.detail = r.item; this.loadChart(row.id); this.loadTimeline(row.id); },
      error: () => {},
    });
  }
  close(): void { this.detail = null; }
  loadChart(id: string): void {
    this.http.get<any>(`${this.base}/chart/${id}`, { params: { period: this.chartPeriod } }).subscribe({ next: r => this.chart = r, error: () => this.chart = null });
  }
  loadTimeline(id: string): void {
    this.http.get<any>(`${this.base}/timeline/${id}`).subscribe({ next: r => this.timeline = r.items ?? [], error: () => this.timeline = [] });
  }
  setPeriod(p: string): void { this.chartPeriod = p; if (this.detail) this.loadChart(this.detail.id); }

  // ── Chart SVG ──
  get series(): number[] { return this.chart ? (this.chart[this.chartMetric] as number[]) : []; }
  get sMax(): number { return Math.max(1, ...this.series); }
  get sMin(): number { return Math.min(...this.series, 0); }
  points(): string {
    const s = this.series; if (!s.length) return '';
    const max = this.sMax, min = Math.min(...s); const range = (max - min) || 1;
    const stepX = s.length > 1 ? 100 / (s.length - 1) : 0;
    return s.map((v, i) => `${(i * stepX).toFixed(2)},${(100 - ((v - min) / range) * 92 - 4).toFixed(2)}`).join(' ');
  }
  area(): string { const p = this.points(); if (!p) return ''; const lastX = this.series.length > 1 ? 100 : 0; return `0,100 ${p} ${lastX},100`; }
  metricColor(): string { return this.chartMetric === 'scores' ? '#6ab0ff' : this.chartMetric === 'descuentos' ? '#ff9f40' : '#00E58F'; }

  money(v: number): string { return `S/ ${(v ?? 0).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
  storeBadge(s: string): string {
    const m: Record<string, string> = { falabella: 'store-falabella', ripley: 'store-ripley', plazavea: 'store-plazavea', oechsle: 'store-oechsle', tottus: 'store-tottus', estilos: 'store-estilos', sodimac: 'store-sodimac', mercadolibre: 'store-mercadolibre', shopstar: 'store-shopstar' };
    return m[s] ?? 'store-default';
  }
  varClass(v: number): string { return v < -0.5 ? 'v-down' : v > 0.5 ? 'v-up' : 'v-eq'; }
}
