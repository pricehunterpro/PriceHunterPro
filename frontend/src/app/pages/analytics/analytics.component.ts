import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { forkJoin, finalize } from 'rxjs';

interface Kpis {
  oportunidadesDetectadas: number;
  gangasDetectadas: number;
  alertasGeneradas: number;
  publicacionesRealizadas: number;
  videosTiktokGenerados: number;
  clicksEstimados: number;
  ctrEstimado: number;
  scorePromedio: number;
}
interface AggRow { store?: string; category?: string; ofertas: number; descuentoPromedio: number; scorePromedio: number; }
interface ChannelRow { canal: string; total: number; publicados: number; programados: number; }
interface Series { period?: string; labels: string[]; ofertas?: number[]; descuentos?: number[]; scores?: number[]; }

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './analytics.component.html',
  styleUrls: ['./analytics.component.css'],
})
export class AnalyticsComponent implements OnInit {
  private http = inject(HttpClient);

  loading = false;
  kpis: Kpis | null = null;
  estimated: string[] = [];
  offersByStore: AggRow[] = [];
  offersByCategory: AggRow[] = [];
  channels: ChannelRow[] = [];
  offersByDay: Series | null = null;
  scoreEvo: Series | null = null;

  // Filtros
  storesList: string[] = [];
  categoriesList: string[] = [];
  fStore = '';
  fCategory = '';
  fChannel = '';
  fMinScore = 0;
  period = '30d';

  readonly periods = [
    { value: '24h', label: '24 horas' },
    { value: '7d',  label: '7 días' },
    { value: '30d', label: '30 días' },
    { value: '90d', label: '90 días' },
  ];
  readonly allChannels = ['Telegram', 'Facebook', 'Instagram', 'TikTok'];

  ngOnInit(): void { this.load(); this.loadFilters(); }

  private base(): Record<string, string> {
    const p: Record<string, string> = {};
    if (this.fStore) p['store'] = this.fStore;
    if (this.fCategory) p['category'] = this.fCategory;
    if (this.fMinScore) p['min_score'] = String(this.fMinScore);
    return p;
  }

  private loadFilters(): void {
    // Reutiliza el endpoint de trends para poblar las listas de filtros
    this.http.get<any>('/api/v1/ai/trends').subscribe({
      next: r => {
        this.storesList = r.filters?.stores ?? [];
        this.categoriesList = r.filters?.categories ?? [];
      },
      error: () => {},
    });
  }

  load(): void {
    this.loading = true;
    const b = this.base();
    const catParams: Record<string, string> = { ...b, limit: '12' };
    const chParams: Record<string, string> = {};
    if (this.fChannel) chParams['channel'] = this.fChannel;
    const tParams: Record<string, string> = { period: this.period };
    if (this.fStore) tParams['store'] = this.fStore;

    forkJoin({
      summary:   this.http.get<any>('/api/v1/bi/analytics/summary', { params: b }),
      byStore:   this.http.get<any>('/api/v1/bi/analytics/offers-by-store', { params: b }),
      byCat:     this.http.get<any>('/api/v1/bi/analytics/offers-by-category', { params: catParams }),
      byDay:     this.http.get<any>('/api/v1/bi/analytics/offers-by-day', { params: tParams }),
      channels:  this.http.get<any>('/api/v1/bi/analytics/publications-by-channel', { params: chParams }),
      scoreEvo:  this.http.get<any>('/api/v1/bi/analytics/score-evolution', { params: tParams }),
    }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.kpis = r.summary?.kpis ?? null;
        this.estimated = r.summary?.estimated ?? [];
        this.offersByStore = r.byStore?.items ?? [];
        this.offersByCategory = r.byCat?.items ?? [];
        this.offersByDay = r.byDay ?? null;
        this.channels = r.channels?.items ?? [];
        this.scoreEvo = r.scoreEvo ?? null;
      },
      error: () => { this.kpis = null; },
    });
  }

  onFilterChange(): void { this.load(); }
  onPeriodChange(p: string): void { this.period = p; this.load(); }
  clearFilters(): void { this.fStore = ''; this.fCategory = ''; this.fChannel = ''; this.fMinScore = 0; this.load(); }

  isEstimated(key: string): boolean { return this.estimated.includes(key); }

  // ── Helpers gráfico ──
  pct(v: number, max: number): number { return Math.round((v / Math.max(1, max)) * 100); }
  get storeMax(): number { return Math.max(1, ...this.offersByStore.map(s => s.ofertas)); }
  get catMax(): number { return Math.max(1, ...this.offersByCategory.map(c => c.ofertas)); }
  get channelMax(): number { return Math.max(1, ...this.channels.map(c => c.total)); }
  get topCategories(): AggRow[] { return this.offersByCategory.slice(0, 6); }

  // Line/area SVG a partir de una serie
  points(series: number[] | undefined): string {
    const s = series ?? [];
    if (!s.length) return '';
    const max = Math.max(1, ...s);
    const W = 100, H = 100;
    const stepX = s.length > 1 ? W / (s.length - 1) : 0;
    return s.map((v, i) => `${(i * stepX).toFixed(2)},${(H - (v / max) * H).toFixed(2)}`).join(' ');
  }
  area(series: number[] | undefined): string {
    const pts = this.points(series);
    if (!pts) return '';
    const s = series ?? [];
    const lastX = s.length > 1 ? 100 : 0;
    return `0,100 ${pts} ${lastX.toFixed(2)},100`;
  }

  channelColor(canal: string): string {
    const m: Record<string, string> = { Telegram: '#29b6f6', Facebook: '#5b7bff', Instagram: '#e1568c', TikTok: '#00e5c0' };
    return m[canal] ?? '#00E58F';
  }
  storeBadge(store: string): string {
    const m: Record<string, string> = {
      falabella: 'store-falabella', ripley: 'store-ripley', plazavea: 'store-plazavea',
      oechsle: 'store-oechsle', tottus: 'store-tottus', estilos: 'store-estilos',
      sodimac: 'store-sodimac', mercadolibre: 'store-mercadolibre',
      shopstar: 'store-shopstar',
    };
    return m[store] ?? 'store-default';
  }
}
