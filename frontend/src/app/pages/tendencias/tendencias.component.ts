import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { forkJoin, finalize } from 'rxjs';

interface Kpis {
  productosMonitoreados: number;
  categoriasActivas: number;
  marcasActivas: number;
  tiendasMonitoreadas: number;
  descuentoPromedio: number;
  margenPromedio: number;
  scorePromedio: number;
}
interface AggRow {
  category?: string; store?: string; brand?: string;
  ofertas?: number; productos?: number;
  descuentoPromedio: number; scorePromedio: number; margenPromedio: number; descuentosAltos: number;
}
interface ProductRow {
  name: string; veces: number; tiendas: string[];
  precioMin: number; precioMax: number; precioProm: number; scorePromedio: number; imageUrl: string;
}
interface Insight { tipo: string; icon: string; titulo: string; }
interface Temporal { period: string; labels: string[]; ofertas: number[]; descuentos: number[]; }

@Component({
  selector: 'app-tendencias',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './tendencias.component.html',
  styleUrls: ['./tendencias.component.css'],
})
export class TendenciasComponent implements OnInit {
  private http = inject(HttpClient);

  loading = false;
  kpis: Kpis | null = null;
  categories: AggRow[] = [];
  stores: AggRow[] = [];
  brands: AggRow[] = [];
  products: ProductRow[] = [];
  insights: Insight[] = [];
  temporal: Temporal | null = null;

  // Filtros
  storesList: string[] = [];
  brandsList: string[] = [];
  categoriesList: string[] = [];
  fStore = '';
  fBrand = '';
  fCategory = '';
  fMinScore = 0;
  period = '7d';

  // Métrica activa del gráfico de categorías
  catMetric: 'ofertas' | 'descuentoPromedio' | 'scorePromedio' = 'ofertas';
  temporalMetric: 'ofertas' | 'descuentos' = 'ofertas';

  readonly periods = [
    { value: '24h', label: '24 horas' },
    { value: '7d',  label: '7 días' },
    { value: '30d', label: '30 días' },
    { value: '90d', label: '90 días' },
  ];

  ngOnInit(): void { this.load(); }

  private params(): Record<string, string> {
    const p: Record<string, string> = {};
    if (this.fStore) p['store'] = this.fStore;
    if (this.fBrand) p['brand'] = this.fBrand;
    if (this.fCategory) p['category'] = this.fCategory;
    if (this.fMinScore) p['min_score'] = String(this.fMinScore);
    return p;
  }

  load(): void {
    this.loading = true;
    const p = this.params();
    forkJoin({
      trends:     this.http.get<any>('/api/v1/ai/trends',            { params: { ...p, period: this.period } }),
      categories: this.http.get<any>('/api/v1/ai/trends/categories', { params: p }),
      stores:     this.http.get<any>('/api/v1/ai/trends/stores',     { params: p }),
      brands:     this.http.get<any>('/api/v1/ai/trends/brands',     { params: { ...p, limit: '20' } }),
      products:   this.http.get<any>('/api/v1/ai/trends/products',   { params: { ...p, limit: '25' } }),
      insights:   this.http.get<any>('/api/v1/ai/trends/insights',   { params: p }),
    }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.kpis = r.trends?.kpis ?? null;
        this.temporal = r.trends?.temporal ?? null;
        this.storesList = r.trends?.filters?.stores ?? [];
        this.brandsList = r.trends?.filters?.brands ?? [];
        this.categoriesList = r.trends?.filters?.categories ?? [];
        this.categories = r.categories?.items ?? [];
        this.stores = r.stores?.items ?? [];
        this.brands = r.brands?.items ?? [];
        this.products = r.products?.items ?? [];
        this.insights = r.insights?.items ?? [];
      },
      error: () => { this.kpis = null; },
    });
  }

  onFilterChange(): void { this.load(); }
  onPeriodChange(p: string): void { this.period = p; this.load(); }
  clearFilters(): void {
    this.fStore = ''; this.fBrand = ''; this.fCategory = ''; this.fMinScore = 0;
    this.load();
  }

  // ── Helpers de gráfico ──
  catValue(c: AggRow): number { return (c as any)[this.catMetric] ?? 0; }
  get catMax(): number { return Math.max(1, ...this.categories.slice(0, 12).map(c => this.catValue(c))); }
  get topCategories(): AggRow[] { return this.categories.slice(0, 12); }

  get storeMax(): number { return Math.max(1, ...this.stores.map(s => s.ofertas ?? 0)); }
  get brandMax(): number { return Math.max(1, ...this.brands.map(b => b.productos ?? 0)); }

  pct(value: number, max: number): number { return Math.round((value / max) * 100); }

  // Heatmap: intensidad 0-1 según ofertas
  heatItems(): AggRow[] { return this.categories.slice(0, 15); }
  heatAlpha(c: AggRow): number {
    const max = Math.max(1, ...this.heatItems().map(x => x.ofertas ?? 0));
    return 0.12 + 0.88 * ((c.ofertas ?? 0) / max);
  }

  // Serie temporal → SVG
  get tSeries(): number[] { return (this.temporal?.[this.temporalMetric] as number[]) ?? []; }
  get tMax(): number { return Math.max(1, ...this.tSeries); }
  get linePoints(): string {
    const s = this.tSeries;
    if (s.length === 0) return '';
    const W = 100, H = 100;
    const stepX = s.length > 1 ? W / (s.length - 1) : 0;
    return s.map((v, i) => `${(i * stepX).toFixed(2)},${(H - (v / this.tMax) * H).toFixed(2)}`).join(' ');
  }
  get areaPoints(): string {
    const pts = this.linePoints;
    if (!pts) return '';
    const s = this.tSeries;
    const W = 100;
    const lastX = s.length > 1 ? W : 0;
    return `0,100 ${pts} ${lastX.toFixed(2)},100`;
  }

  storeBadge(store: string): string {
    const m: Record<string, string> = {
      falabella: 'store-falabella', ripley: 'store-ripley', plazavea: 'store-plazavea',
      oechsle: 'store-oechsle', tottus: 'store-tottus', estilos: 'store-estilos',
      sodimac: 'store-sodimac', mercadolibre: 'store-mercadolibre',
    };
    return m[store] ?? 'store-default';
  }
  cap(s: string): string { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
}
