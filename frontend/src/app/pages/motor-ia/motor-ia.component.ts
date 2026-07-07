import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';
import { DealsStateService } from '../../services/deals-state.service';

export interface ScoredDeal {
  id: string; store: string; name: string; brand: string; category: string;
  url: string; imageUrl: string;
  currentPrice: number; originalPrice: number; discountPct: number;
  marginPct: number; inStock: boolean; scrapedAt: string;
  avgMarketPrice: number; belowMarket: boolean; mktDiffPct: number;
  score: number;
  clasificacion: string;
  clasificacionEmoji: string;
  recomendacion: string;
  explicacion: string;
}

interface Kpis {
  totalAnalizadas: number; gangasExtremas: number;
  excelentesOfertas: number; buenasOfertas: number;
  ofertasNormales: number; promedioScore: number;
}

interface AiResponse {
  items: ScoredDeal[]; total: number;
  kpis: Kpis;
  filters: { stores: string[]; categories: string[] };
}

@Component({
  selector: 'app-motor-ia',
  templateUrl: './motor-ia.component.html',
  styleUrls: ['./motor-ia.component.css'],
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class MotorIaComponent implements OnInit {
  private http = inject(HttpClient);
  protected s  = inject(DealsStateService);

  deals:    ScoredDeal[] = [];
  kpis:     Kpis = { totalAnalizadas: 0, gangasExtremas: 0, excelentesOfertas: 0, buenasOfertas: 0, ofertasNormales: 0, promedioScore: 0 };
  stores:   string[] = [];
  categories: string[] = [];

  loading   = false;
  error     = '';
  total     = 0;

  // Filtros
  filterStore         = '';
  filterCategory      = '';
  filterClasificacion = '';
  filterMinScore      = 0;
  sortBy              = 'score';
  currentPage         = 1;
  readonly pageSize   = 50;

  get totalPages(): number { return Math.ceil(this.total / this.pageSize); }

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true; this.error = '';
    const params: Record<string, any> = {
      sort:          this.sortBy,
      min_score:     this.filterMinScore,
      page:          this.currentPage,
      limit:         this.pageSize,
    };
    if (this.filterStore)         params['store']         = this.filterStore;
    if (this.filterCategory)      params['category']      = this.filterCategory;
    if (this.filterClasificacion) params['clasificacion']  = this.filterClasificacion;

    this.http.get<AiResponse>('/api/v1/ai/score-opportunities', { params })
      .pipe(finalize(() => this.loading = false))
      .subscribe({
        next: r => {
          this.deals      = r.items ?? [];
          this.total      = r.total ?? 0;
          this.kpis       = r.kpis;
          this.stores     = r.filters?.stores ?? [];
          this.categories = r.filters?.categories ?? [];
        },
        error: () => { this.error = 'No se pudo conectar con el Motor IA.'; this.deals = []; },
      });
  }

  applyFilters(): void { this.currentPage = 1; this.load(); }
  clearFilters(): void {
    this.filterStore = ''; this.filterCategory = '';
    this.filterClasificacion = ''; this.filterMinScore = 0;
    this.sortBy = 'score'; this.currentPage = 1;
    this.load();
  }
  goToPage(p: number): void {
    if (p < 1 || p > this.totalPages) return;
    this.currentPage = p; this.load();
  }

  scoreClass(score: number): string {
    if (score >= 95) return 'score-extreme';
    if (score >= 80) return 'score-excellent';
    if (score >= 60) return 'score-good';
    return 'score-normal';
  }

  badgeClass(clasificacion: string): string {
    if (clasificacion === 'Ganga Extrema')    return 'badge-extreme';
    if (clasificacion === 'Excelente Oferta') return 'badge-excellent';
    if (clasificacion === 'Buena Oferta')     return 'badge-good';
    return 'badge-normal';
  }

  recomClass(r: string): string {
    if (r.includes('Publicar')) return 'recom-publish';
    if (r === 'Comprar')        return 'recom-buy';
    if (r === 'Revisar')        return 'recom-review';
    return 'recom-ignore';
  }

  scoreBar(score: number): string {
    if (score >= 95) return '#ff4d00';
    if (score >= 80) return '#00E58F';
    if (score >= 60) return '#ffd700';
    return '#5a5a6e';
  }

  enviarPublicador(deal: ScoredDeal): void {
    // Preparado para conectar con Publicador IA en FASE 4
    console.log('[PublicadorIA] deal queued:', deal.id, deal.name);
    alert(`"${deal.name}" añadido a la cola del Publicador IA (FASE 4)`);
  }
}
