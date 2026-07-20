import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { forkJoin, finalize } from 'rxjs';

interface Kpis {
  gananciaPotencialTotal: number;
  roiPromedio: number;
  productosRentables: number;
  capitalRequerido: number;
  mayorMargenDetectado: number;
}
interface Clasif { alta: number; buena: number; media: number; baja: number; }
interface ProfitRow {
  id: string; name: string; store: string; category: string; imageUrl: string; url: string;
  precioCompra: number; precioSugerido: number; ganancia: number; roi: number;
  margen: number; score: number; clasificacion: string; recomendacion: string;
}

@Component({
  selector: 'app-rentabilidad',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './rentabilidad.component.html',
  styleUrls: ['./rentabilidad.component.css'],
})
export class RentabilidadComponent implements OnInit {
  private http = inject(HttpClient);

  loading = false;
  kpis: Kpis | null = null;
  clasif: Clasif | null = null;
  items: ProfitRow[] = [];

  storesList: string[] = [];
  categoriesList: string[] = [];
  fStore = '';
  fCategory = '';
  fMinScore = 0;
  fClas = '';
  sort = 'roi';

  readonly sortOptions = [
    { value: 'roi',      label: 'ROI' },
    { value: 'ganancia', label: 'Ganancia estimada' },
    { value: 'score',    label: 'Score PriceHunter' },
    { value: 'margen',   label: 'Margen' },
  ];
  readonly clasOptions = ['Alta rentabilidad', 'Buena rentabilidad', 'Rentabilidad media', 'Baja rentabilidad'];

  ngOnInit(): void { this.loadFilters(); this.load(); }

  private base(): Record<string, string> {
    const p: Record<string, string> = {};
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
    const prodParams: Record<string, string> = { ...b, sort: this.sort, limit: '100' };
    if (this.fClas) prodParams['clasificacion'] = this.fClas;
    forkJoin({
      summary:  this.http.get<any>('/api/v1/bi/profitability/summary', { params: b }),
      products: this.http.get<any>('/api/v1/bi/profitability/products', { params: prodParams }),
    }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.kpis = r.summary?.kpis ?? null;
        this.clasif = r.summary?.clasificaciones ?? null;
        this.items = r.products?.items ?? [];
      },
      error: () => { this.kpis = null; this.items = []; },
    });
  }

  onFilterChange(): void { this.load(); }
  clearFilters(): void { this.fStore = ''; this.fCategory = ''; this.fMinScore = 0; this.fClas = ''; this.sort = 'roi'; this.load(); }
  toggleClas(c: string): void { this.fClas = this.fClas === c ? '' : c; this.load(); }

  clasClass(c: string): string {
    if (c === 'Alta rentabilidad')  return 'alta';
    if (c === 'Buena rentabilidad') return 'buena';
    if (c === 'Rentabilidad media') return 'media';
    return 'baja';
  }
  get clasTotal(): number { const c = this.clasif; return c ? (c.alta + c.buena + c.media + c.baja) || 1 : 1; }

  storeBadge(store: string): string {
    const m: Record<string, string> = {
      falabella: 'store-falabella', ripley: 'store-ripley', plazavea: 'store-plazavea',
      oechsle: 'store-oechsle', tottus: 'store-tottus', estilos: 'store-estilos',
      sodimac: 'store-sodimac', mercadolibre: 'store-mercadolibre',
      shopstar: 'store-shopstar',
    };
    return m[store] ?? 'store-default';
  }
  money(v: number): string { return `S/ ${(v ?? 0).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
}
