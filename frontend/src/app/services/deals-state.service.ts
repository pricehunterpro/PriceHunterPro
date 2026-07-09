import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

export interface Deal {
  id: string; store: string; name: string; brand: string; category: string;
  url: string; currentPrice: number; originalPrice: number; discountPct: number;
  marginPct: number; imageUrl: string; inStock: boolean; scrapedAt: string;
  avgMarketPrice: number; belowMarket: boolean; mktDiffPct: number;
}
export interface DealResponse {
  items: Deal[]; total: number;
  filters: { categories: string[]; brands: string[]; stores: string[]; };
}
export interface StatsResponse {
  total: number; bestDiscount: number; bestMargin: number; minPrice: number;
  lastSync: string; byStore: Record<string, number>;
}

@Injectable({ providedIn: 'root' })
export class DealsStateService {
  private http = inject(HttpClient);

  stats: StatsResponse | null = null;
  lastSyncRaw = '';
  categories: string[] = [];
  brands: string[] = [];
  stores: string[] = [];

  deals: Deal[] = [];
  loading = false;
  error = '';
  searchQuery = '';
  selectedCategory = '';
  selectedBrand = '';
  selectedStore = '';
  sortBy = 'discount';
  currentPage = 1;
  totalItems = 0;
  readonly pageSize = 50;

  alertDeals: Deal[] = [];
  alertsTotal = 0;
  loadingAlerts = false;

  gangaDeals: Deal[] = [];
  gangasTotal = 0;
  loadingGangas = false;
  gangaSort = 'discount';
  gangaStore = '';

  isAdmin = false;
  scraping = false;
  scrapeMsg = '';

  private _ready = false;

  init(): void {
    if (this._ready) return;
    this._ready = true;
    const keyInUrl = new URLSearchParams(window.location.search).get('key') === 'ph2026';
    if (keyInUrl) sessionStorage.setItem('ph_admin', '1');
    this.isAdmin = keyInUrl || sessionStorage.getItem('ph_admin') === '1';
    this.loadStats();
    this.loadDeals();
    this.loadAlerts();
    this.loadGangas();
    this.checkScrapeStatus();
  }

  private _pollTimer: any = null;

  checkScrapeStatus(): void {
    this.http.get<{ running: boolean; task_id: string | null; state?: string }>(
      '/api/v1/deals/scrape/status'
    ).subscribe({
      next: r => {
        if (r.running) {
          this.scraping = true;
          this.scrapeMsg = `En proceso · ID ${(r.task_id ?? '').slice(0, 8)}`;
          clearTimeout(this._pollTimer);
          this._pollTimer = setTimeout(() => this.checkScrapeStatus(), 15000);
        } else if (this.scraping) {
          this.scraping = false;
          this.scrapeMsg = '';
          this.loadStats();
          this.loadDeals();
          this.loadGangas();
        }
      },
      error: () => {},
    });
  }

  get totalPages(): number { return Math.ceil(this.totalItems / this.pageSize); }

  get lastSyncLabel(): string {
    if (!this.lastSyncRaw || this.lastSyncRaw === 'Nunca') return 'Sin datos';
    const d = new Date(this.lastSyncRaw);
    if (isNaN(d.getTime())) return 'Sin datos';
    const min = Math.floor((Date.now() - d.getTime()) / 60000);
    if (min < 1)  return 'hace menos de 1 min';
    if (min < 60) return `hace ${min} min`;
    const h = Math.floor(min / 60);
    if (h < 24)   return `hace ${h} h`;
    return d.toLocaleDateString('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  get lastSyncFull(): string {
    if (!this.lastSyncRaw || this.lastSyncRaw === 'Nunca') return '--';
    const d = new Date(this.lastSyncRaw);
    if (isNaN(d.getTime())) return '--';
    return d.toLocaleDateString('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  get activeFilters(): string[] {
    const f: string[] = [];
    if (this.searchQuery.trim())  f.push(this.searchQuery.trim());
    if (this.selectedCategory)    f.push(`Cat: ${this.selectedCategory}`);
    if (this.selectedBrand)       f.push(`Marca: ${this.selectedBrand}`);
    if (this.selectedStore)       f.push(`Tienda: ${this.selectedStore}`);
    return f;
  }

  loadStats(): void {
    this.http.get<StatsResponse>('/api/v1/deals/stats').subscribe({
      next: r => { this.stats = r; this.lastSyncRaw = r.lastSync ?? ''; },
      error: () => { this.stats = null; },
    });
  }

  loadDeals(): void {
    this.loading = true; this.error = '';
    this.http.get<DealResponse>('/api/v1/deals', { params: {
      q: this.searchQuery, store: this.selectedStore,
      category: this.selectedCategory, brand: this.selectedBrand,
      sort: this.sortBy, min_discount: 5, page: this.currentPage, limit: this.pageSize,
    }}).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.deals = r.items ?? []; this.totalItems = r.total ?? 0;
        this.categories = r.filters?.categories ?? [];
        this.brands     = r.filters?.brands ?? [];
        this.stores     = r.filters?.stores ?? [];
      },
      error: () => { this.error = 'No se pudo conectar con la API.'; this.deals = []; },
    });
  }

  loadAlerts(): void {
    this.loadingAlerts = true;
    this.http.get<DealResponse>('/api/v1/deals', {
      params: { below_market: true, sort: 'market_diff', limit: 200, page: 1 },
    }).pipe(finalize(() => this.loadingAlerts = false)).subscribe({
      next: r => { this.alertDeals = r.items ?? []; this.alertsTotal = r.total ?? 0; },
      error: () => { this.alertDeals = []; this.alertsTotal = 0; },
    });
  }

  loadGangas(): void {
    this.loadingGangas = true;
    const params: Record<string, any> = { min_discount: 40, min_price: 50, sort: this.gangaSort, limit: 300, page: 1 };
    if (this.gangaStore) params['store'] = this.gangaStore;
    this.http.get<DealResponse>('/api/v1/deals', { params })
      .pipe(finalize(() => this.loadingGangas = false)).subscribe({
        next: r => { this.gangaDeals = r.items ?? []; this.gangasTotal = r.total ?? 0; },
        error: () => { this.gangaDeals = []; this.gangasTotal = 0; },
      });
  }

  onStoreChange(): void {
    this.selectedCategory = '';
    this.selectedBrand = '';
    this.currentPage = 1;
    this.loadDeals();
  }

  onCategoryChange(): void {
    this.selectedBrand = '';
    this.currentPage = 1;
    this.loadDeals();
  }

  submitFilters(): void { this.currentPage = 1; this.loadDeals(); }

  clearAllFilters(): void {
    this.searchQuery = ''; this.selectedCategory = '';
    this.selectedBrand = ''; this.selectedStore = '';
    this.sortBy = 'discount'; this.currentPage = 1;
    this.loadDeals();
  }

  clearFilter(f: 'category' | 'brand' | 'store'): void {
    if (f === 'store')    { this.selectedStore = ''; this.selectedCategory = ''; this.selectedBrand = ''; }
    if (f === 'category') { this.selectedCategory = ''; this.selectedBrand = ''; }
    if (f === 'brand')    { this.selectedBrand = ''; }
    this.loadDeals();
  }

  goToPage(p: number): void {
    if (p < 1 || p > this.totalPages) return;
    this.currentPage = p; this.loadDeals();
  }

  triggerScrape(): void {
    if (this.scraping) return;
    this.scraping = true; this.scrapeMsg = '';
    this.http.post<{ task_id: string }>('/api/v1/deals/scrape/trigger', {}).subscribe({
      next: r => {
        this.scrapeMsg = `En proceso · ID ${r.task_id.slice(0, 8)}`;
        clearTimeout(this._pollTimer);
        this._pollTimer = setTimeout(() => this.checkScrapeStatus(), 15000);
      },
      error: () => { this.scraping = false; this.scrapeMsg = 'Error al conectar'; },
    });
  }

  formatCurrency = (v: number) => `S/ ${v.toFixed(2)}`;

  getStoreBadgeClass(store: string): string {
    const m: Record<string, string> = {
      falabella: 'store-falabella', ripley: 'store-ripley', plazavea: 'store-plazavea',
      oechsle: 'store-oechsle', promart: 'store-promart', tottus: 'store-tottus', hiraoka: 'store-hiraoka', estilos: 'store-estilos', sodimac: 'store-sodimac', mercadolibre: 'store-mercadolibre',
    };
    return m[store] ?? 'store-default';
  }

  productAge(at: string): { label: string; level: 'fresh' | 'recent' | 'stale' } {
    if (!at) return { label: 'sin datos', level: 'stale' };
    const d = new Date(at);
    if (isNaN(d.getTime())) return { label: 'sin datos', level: 'stale' };
    const min = Math.floor((Date.now() - d.getTime()) / 60000);
    if (min < 60)  return { label: `hace ${min < 1 ? '<1' : min} min`, level: 'fresh' };
    const h = Math.floor(min / 60);
    if (h < 2)     return { label: `hace ${h} h`, level: 'recent' };
    return { label: `hace ${h} h`, level: 'stale' };
  }
}
