import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { forkJoin, finalize } from 'rxjs';

interface TopItem {
  id: string; ranking: number; name: string; store: string; category: string;
  imageUrl: string; url: string;
  currentPrice: number; avgMarketPrice: number; precioSugerido: number;
  discountPct: number; marginPct: number; roi: number; score: number;
  clasificacion: string; clasificacionEmoji: string; recomendacion: string;
  clicksEstimados: number; popularidad: number; frecuencia: number;
}
interface Kpis {
  productoTopDelDia: string; productoTopScore: number; productoTopStore: string;
  mejorScore: number; mayorRoi: number; mayorDescuento: number; categoriaDominante: string;
}

@Component({
  selector: 'app-top-productos',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './top-productos.component.html',
  styleUrls: ['./top-productos.component.css'],
})
export class TopProductosComponent implements OnInit {
  private http   = inject(HttpClient);
  private router = inject(Router);

  loading = false;
  items: TopItem[] = [];
  kpis: Kpis | null = null;
  storesList: string[] = [];
  categoriesList: string[] = [];

  period = '30d';
  sort = 'score';
  fStore = '';
  fCategory = '';
  fMinScore = 0;

  selected: TopItem | null = null;
  toast = '';
  private toastTimer: any = null;

  readonly periods = [
    { value: 'hoy', label: 'Hoy' },
    { value: '7d',  label: '7 días' },
    { value: '30d', label: '30 días' },
    { value: '90d', label: '90 días' },
  ];
  readonly sortOptions = [
    { value: 'score',       label: 'Score PriceHunter' },
    { value: 'roi',         label: 'ROI' },
    { value: 'margen',      label: 'Margen' },
    { value: 'descuento',   label: 'Descuento' },
    { value: 'clicks',      label: 'Clicks estimados' },
    { value: 'popularidad', label: 'Popularidad' },
    { value: 'frecuencia',  label: 'Frecuencia detectada' },
  ];

  ngOnInit(): void { this.loadFilters(); this.load(); }

  private base(): Record<string, string> {
    const p: Record<string, string> = { period: this.period };
    if (this.fStore) p['store'] = this.fStore;
    if (this.fCategory) p['category'] = this.fCategory;
    if (this.fMinScore) p['min_score'] = String(this.fMinScore);
    return p;
  }
  private loadFilters(): void {
    this.http.get<any>('/api/v1/ai/trends').subscribe({
      next: r => { this.storesList = r.filters?.stores ?? []; this.categoriesList = r.filters?.categories ?? []; },
      error: () => {},
    });
  }

  load(): void {
    this.loading = true;
    const b = this.base();
    forkJoin({
      list:    this.http.get<any>('/api/v1/bi/top-products', { params: { ...b, sort: this.sort, limit: '100' } }),
      summary: this.http.get<any>('/api/v1/bi/top-products/summary', { params: b }),
    }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.list?.items ?? []; this.kpis = r.summary?.kpis ?? null; },
      error: () => { this.items = []; this.kpis = null; },
    });
  }

  onFilterChange(): void { this.load(); }
  onPeriodChange(p: string): void { this.period = p; this.load(); }
  clearFilters(): void { this.fStore = ''; this.fCategory = ''; this.fMinScore = 0; this.sort = 'score'; this.load(); }

  clasClass(c: string): string {
    if (c === 'Ganga Extrema')    return 'extreme';
    if (c === 'Excelente Oferta') return 'excellent';
    if (c === 'Buena Oferta')     return 'good';
    return 'normal';
  }
  roiClass(roi: number): string {
    if (roi > 50) return 'alta';
    if (roi >= 25) return 'buena';
    if (roi >= 10) return 'media';
    return 'baja';
  }

  // ── Acciones ──
  verDetalle(it: TopItem): void { this.selected = it; }
  closeDetail(): void { this.selected = null; }
  enviarPublicador(it: TopItem, ev?: Event): void { ev?.stopPropagation(); this.showToast(`Enviado a Publicador IA: ${it.name.slice(0, 28)}…`); }
  enviarTiktok(it: TopItem, ev?: Event): void { ev?.stopPropagation(); this.showToast(`Enviado a TikTok Factory: ${it.name.slice(0, 28)}…`); }

  agregarPortafolio(it: TopItem, ev?: Event): void {
    ev?.stopPropagation();
    const body = {
      opportunity_id: it.id, product_name: it.name, store: it.store, category: it.category,
      quantity: 1, purchase_price: it.currentPrice, suggested_sale_price: it.precioSugerido,
      status: 'Comprado', image_url: it.imageUrl,
    };
    this.http.post('/api/v1/bi/portfolio', body).subscribe({
      next: () => this.showToast(`✔ Agregado al portafolio: ${it.name.slice(0, 26)}…`),
      error: () => this.showToast('Error al agregar al portafolio'),
    });
  }
  irPortafolio(): void { this.router.navigate(['/business-intelligence/portafolio']); }

  private showToast(msg: string): void {
    this.toast = msg;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast = '', 2800);
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
  money(v: number): string { return `S/ ${(v ?? 0).toFixed(2)}`; }
}
