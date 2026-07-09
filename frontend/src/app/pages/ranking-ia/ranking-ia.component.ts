import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';

interface RankItem {
  id: string;
  posicion: number;
  name: string;
  brand: string;
  store: string;
  category: string;
  currentPrice: number;
  originalPrice: number;
  avgMarketPrice: number;
  discountPct: number;
  marginPct: number;
  mktDiffPct: number;
  belowMarket: boolean;
  inStock: boolean;
  imageUrl: string;
  url: string;
  score: number;
  clasificacion: string;
  clasificacionEmoji: string;
  recomendacion: string;
  explicacion: string;
}
interface Kpis {
  topOportunidades: number;
  scorePromedioTop10: number;
  mayorMargen: number;
  mayorDescuento: number;
  mejorTienda: string;
  mejorTiendaScore: number;
}

const FAV_KEY = 'ph_ranking_favs';

@Component({
  selector: 'app-ranking-ia',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './ranking-ia.component.html',
  styleUrls: ['./ranking-ia.component.css'],
})
export class RankingIaComponent implements OnInit {
  private http   = inject(HttpClient);
  private router = inject(Router);

  items: RankItem[] = [];
  kpis: Kpis | null = null;
  stores: string[] = [];
  categories: string[] = [];
  loading = false;

  sort = 'score';
  filterStore = '';
  filterCategory = '';

  readonly sortOptions = [
    { value: 'score',    label: 'Score PriceHunter' },
    { value: 'margin',   label: 'Margen estimado' },
    { value: 'discount', label: 'Descuento' },
    { value: 'price',    label: 'Precio mínimo' },
    { value: 'store',    label: 'Tienda' },
    { value: 'category', label: 'Categoría' },
  ];

  selected: RankItem | null = null;
  favs = new Set<string>();
  toast = '';
  private toastTimer: any = null;

  ngOnInit(): void {
    this.loadFavs();
    this.load();
  }

  load(): void {
    this.loading = true;
    const params: Record<string, string> = { sort: this.sort, limit: '100' };
    if (this.filterStore) params['store'] = this.filterStore;
    if (this.filterCategory) params['category'] = this.filterCategory;
    this.http.get<{ items: RankItem[]; kpis: Kpis; filters: { stores: string[]; categories: string[] } }>(
      '/api/v1/ai/ranking', { params },
    ).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.items = r.items ?? [];
        this.kpis = r.kpis ?? null;
        this.stores = r.filters?.stores ?? [];
        this.categories = r.filters?.categories ?? [];
      },
      error: () => { this.items = []; this.kpis = null; },
    });
  }

  onSortChange(): void { this.load(); }
  onFilterChange(): void { this.load(); }
  clearFilters(): void { this.filterStore = ''; this.filterCategory = ''; this.sort = 'score'; this.load(); }

  // ── Clasificación → clase de color ──
  clasClass(c: string): string {
    if (c === 'Ganga Extrema')    return 'extreme';
    if (c === 'Excelente Oferta') return 'excellent';
    if (c === 'Buena Oferta')     return 'good';
    return 'normal';
  }

  // ── Favoritos (localStorage) ──
  private loadFavs(): void {
    try {
      const raw = localStorage.getItem(FAV_KEY);
      this.favs = new Set(raw ? JSON.parse(raw) : []);
    } catch { this.favs = new Set(); }
  }
  isFav(id: string): boolean { return this.favs.has(id); }
  toggleFav(item: RankItem, ev?: Event): void {
    ev?.stopPropagation();
    if (this.favs.has(item.id)) { this.favs.delete(item.id); this.showToast('Quitado de favoritos'); }
    else { this.favs.add(item.id); this.showToast('★ Agregado a favoritos'); }
    localStorage.setItem(FAV_KEY, JSON.stringify([...this.favs]));
  }

  // ── Acciones ──
  verDetalle(item: RankItem): void { this.selected = item; }
  closeDetail(): void { this.selected = null; }

  enviarPublicador(item: RankItem, ev?: Event): void {
    ev?.stopPropagation();
    this.showToast(`Enviado a Publicador IA: ${item.name.slice(0, 30)}…`);
  }
  enviarTiktok(item: RankItem, ev?: Event): void {
    ev?.stopPropagation();
    this.showToast(`Enviado a TikTok Factory: ${item.name.slice(0, 30)}…`);
  }
  irPublicador(): void { this.router.navigate(['/marketing/publicador-ia']); }

  private showToast(msg: string): void {
    this.toast = msg;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast = '', 2600);
  }

  storeBadge(store: string): string {
    const m: Record<string, string> = {
      falabella: 'store-falabella', ripley: 'store-ripley', plazavea: 'store-plazavea',
      oechsle: 'store-oechsle', tottus: 'store-tottus', estilos: 'store-estilos',
      sodimac: 'store-sodimac', mercadolibre: 'store-mercadolibre',
    };
    return m[store] ?? 'store-default';
  }
  fmt(v: number): string { return `S/ ${(v ?? 0).toFixed(2)}`; }
}
