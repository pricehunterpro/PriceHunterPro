import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';

export interface Recommendation {
  id: string;
  opportunity_id: string;
  product_name: string;
  store: string;
  category: string;
  brand: string;
  current_price: number;
  historical_price: number;
  original_price: number;
  discount_percent: number;
  estimated_margin: number;
  pricehunter_score: number;
  recommendation_type: string;
  priority: string;
  reason: string;
  status: string;
  created_at: string;
  updated_at: string;
  // contexto
  clasificacion: string;
  viralidad: number;
  ranking_pos: number;
  category_avg_discount: number;
  below_market: boolean;
  mkt_diff_pct: number;
  in_stock: boolean;
  image_url: string;
  url: string;
}

interface Kpis {
  recomendacionesGeneradas: number;
  recomendacionesCompra: number;
  recomendacionesPublicacion: number;
  recomendacionesRevision: number;
  scorePromedioRecomendado: number;
  roiPromedioEstimado: number;
  recomendacionesIgnorar: number;
}

interface Destacados {
  comprarHoy: Recommendation | null;
  publicarPrimero: Recommendation | null;
  mejorRoi: Recommendation | null;
  masViral: Recommendation | null;
  ignorar: number;
}

interface Filters {
  tipos: string[];
  prioridades: string[];
  estados: string[];
  stores: string[];
  categories: string[];
}

interface ApiResponse {
  items: Recommendation[];
  total: number;
  kpis: Kpis;
  destacados: Destacados;
  filters: Filters;
}

const API = '/api/v1/ai/recommendations';

@Component({
  selector: 'app-recomendaciones',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './recomendaciones.component.html',
  styleUrls: ['./recomendaciones.component.css'],
})
export class RecomendacionesComponent implements OnInit {
  private http = inject(HttpClient);
  private router = inject(Router);

  items: Recommendation[] = [];
  total = 0;
  kpis: Kpis | null = null;
  destacados: Destacados | null = null;
  filters: Filters = { tipos: [], prioridades: [], estados: [], stores: [], categories: [] };
  loading = false;
  error = '';

  // ── Filtros ──
  fTipo = '';
  fPrioridad = '';
  fStore = '';
  fCategory = '';
  fMinScore = 0;
  fDesde = '';
  fQuery = '';
  sort = 'priority';
  page = 1;
  readonly limit = 50;

  readonly sortOptions = [
    { value: 'priority', label: 'Prioridad' },
    { value: 'score', label: 'Score IA' },
    { value: 'roi', label: 'ROI estimado' },
    { value: 'discount', label: 'Descuento' },
    { value: 'viral', label: 'Viralidad' },
    { value: 'price_asc', label: 'Precio más bajo' },
  ];

  selected: Recommendation | null = null;
  busy = new Set<string>();
  toast = '';
  private toastTimer: any = null;

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    this.error = '';
    const params: Record<string, string> = {
      sort: this.sort,
      page: String(this.page),
      limit: String(this.limit),
    };
    if (this.fTipo) params['tipo'] = this.fTipo;
    if (this.fPrioridad) params['prioridad'] = this.fPrioridad;
    if (this.fStore) params['store'] = this.fStore;
    if (this.fCategory) params['category'] = this.fCategory;
    if (this.fMinScore > 0) params['min_score'] = String(this.fMinScore);
    if (this.fDesde) params['desde'] = this.fDesde;
    if (this.fQuery.trim()) params['q'] = this.fQuery.trim();

    this.http.get<ApiResponse>(API, { params })
      .pipe(finalize(() => (this.loading = false)))
      .subscribe({
        next: r => {
          this.items = r.items ?? [];
          this.total = r.total ?? 0;
          this.kpis = r.kpis ?? null;
          this.destacados = r.destacados ?? null;
          if (r.filters) this.filters = r.filters;
        },
        error: () => {
          this.items = [];
          this.total = 0;
          this.kpis = null;
          this.destacados = null;
          this.error = 'No se pudieron cargar las recomendaciones.';
        },
      });
  }

  onFilterChange(): void { this.page = 1; this.load(); }

  clearFilters(): void {
    this.fTipo = ''; this.fPrioridad = ''; this.fStore = ''; this.fCategory = '';
    this.fMinScore = 0; this.fDesde = ''; this.fQuery = ''; this.sort = 'priority';
    this.page = 1;
    this.load();
  }

  get totalPages(): number { return Math.max(1, Math.ceil(this.total / this.limit)); }
  goPage(p: number): void {
    if (p < 1 || p > this.totalPages) return;
    this.page = p;
    this.load();
  }

  // ── Filtro rápido desde las tarjetas de respuesta ──
  filtrarPor(tipo: string): void {
    this.fTipo = this.fTipo === tipo ? '' : tipo;
    this.onFilterChange();
  }

  // ── Badges ──
  tipoClass(tipo: string): string {
    switch (tipo) {
      case 'Comprar y Publicar':      return 'rec-both';
      case 'Comprar':                 return 'rec-buy';
      case 'Publicar':                return 'rec-pub';
      case 'Enviar a Publicador IA':  return 'rec-pubia';
      case 'Enviar a TikTok Factory': return 'rec-tk';
      case 'Revisar':                 return 'rec-rev';
      default:                        return 'rec-ign';
    }
  }

  prioClass(p: string): string {
    if (p === 'Alta') return 'prio-alta';
    if (p === 'Media') return 'prio-media';
    return 'prio-baja';
  }

  estadoClass(e: string): string {
    switch (e) {
      case 'Revisada':             return 'st-rev';
      case 'Enviada a Publicador': return 'st-pub';
      case 'Enviada a TikTok':     return 'st-tk';
      case 'Ignorada':             return 'st-ign';
      default:                     return 'st-new';
    }
  }

  scoreClass(score: number): string {
    if (score >= 95) return 'extreme';
    if (score >= 80) return 'excellent';
    if (score >= 60) return 'good';
    return 'normal';
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

  // ── Detalle ──
  verDetalle(rec: Recommendation): void { this.selected = rec; }
  closeDetail(): void { this.selected = null; }

  // ── Acciones ──
  private accion(rec: Recommendation, path: string, okMsg: string, nuevoEstado: string, ev?: Event): void {
    ev?.stopPropagation();
    if (this.busy.has(rec.id)) return;
    this.busy.add(rec.id);
    this.http.post<{ status: string }>(`${API}/${rec.id}/${path}`, {})
      .pipe(finalize(() => this.busy.delete(rec.id)))
      .subscribe({
        next: () => {
          rec.status = nuevoEstado;
          if (this.selected?.id === rec.id) this.selected.status = nuevoEstado;
          this.showToast(okMsg);
        },
        error: () => this.showToast('No se pudo completar la acción'),
      });
  }

  marcarRevisado(rec: Recommendation, ev?: Event): void {
    this.accion(rec, 'mark-reviewed', '✓ Marcada como revisada', 'Revisada', ev);
  }
  ignorar(rec: Recommendation, ev?: Event): void {
    this.accion(rec, 'ignore', 'Recomendación ignorada', 'Ignorada', ev);
  }
  enviarPublicador(rec: Recommendation, ev?: Event): void {
    this.accion(rec, 'send-to-publisher', 'Enviada a Publicador IA', 'Enviada a Publicador', ev);
  }
  enviarTiktok(rec: Recommendation, ev?: Event): void {
    this.accion(rec, 'send-to-tiktok', 'Enviada a TikTok Factory', 'Enviada a TikTok', ev);
  }
  agregarPortafolio(rec: Recommendation, ev?: Event): void {
    this.accion(rec, 'add-to-portfolio', 'Agregada al Portafolio', 'Revisada', ev);
  }

  irPublicador(): void { this.router.navigate(['/marketing/publicador-ia']); }
  irTiktok(): void { this.router.navigate(['/marketing/tiktok-factory']); }

  isBusy(rec: Recommendation): boolean { return this.busy.has(rec.id); }

  private showToast(msg: string): void {
    this.toast = msg;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => (this.toast = ''), 2600);
  }

  fmt(v: number): string { return `S/ ${(v ?? 0).toFixed(2)}`; }
  short(v: string, n = 40): string {
    if (!v) return '';
    return v.length > n ? `${v.slice(0, n)}…` : v;
  }
}
