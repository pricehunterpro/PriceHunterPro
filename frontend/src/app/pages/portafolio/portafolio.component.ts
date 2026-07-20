import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface PortfolioItem {
  id: string;
  opportunity_id: string | null;
  product_name: string;
  store: string;
  category: string;
  quantity: number;
  purchase_price: number;
  total_cost: number;
  suggested_sale_price: number;
  final_sale_price: number;
  estimated_profit: number;
  real_profit: number;
  roi: number;
  status: string;
  purchase_date: string;
  sale_date: string | null;
  notes: string;
  image_url?: string;
  created_at: string;
  updated_at: string;
}
interface Kpis {
  inversionTotal: number;
  gananciaEstimada: number;
  gananciaReal: number;
  productosEnPortafolio: number;
  productosVendidos: number;
  roiPromedio: number;
}

const EMPTY = (): Partial<PortfolioItem> => ({
  product_name: '', store: '', category: 'General', quantity: 1,
  purchase_price: 0, suggested_sale_price: 0, final_sale_price: 0,
  status: 'Comprado', notes: '',
});

@Component({
  selector: 'app-portafolio',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './portafolio.component.html',
  styleUrls: ['./portafolio.component.css'],
})
export class PortafolioComponent implements OnInit {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/bi/portfolio';

  loading = false;
  items: PortfolioItem[] = [];
  kpis: Kpis | null = null;
  porEstado: Record<string, number> = {};
  estados: string[] = ['Comprado', 'En tránsito', 'Recibido', 'Publicado', 'Vendido', 'Cancelado'];
  filterStatus = '';

  // Modal form
  showForm = false;
  editing: string | null = null;
  form: Partial<PortfolioItem> = EMPTY();
  saving = false;

  // Detalle
  detail: PortfolioItem | null = null;
  toast = '';
  private toastTimer: any = null;

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    const params: Record<string, string> = {};
    if (this.filterStatus) params['status'] = this.filterStatus;
    this.http.get<any>(this.base, { params }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.items ?? []; this.estados = r.estados ?? this.estados; },
      error: () => { this.items = []; },
    });
    this.loadSummary();
  }
  loadSummary(): void {
    this.http.get<any>(`${this.base}/summary`).subscribe({
      next: r => { this.kpis = r.kpis ?? null; this.porEstado = r.porEstado ?? {}; },
      error: () => {},
    });
  }
  setFilter(s: string): void { this.filterStatus = this.filterStatus === s ? '' : s; this.load(); }

  // ── Form ──
  openAdd(): void { this.editing = null; this.form = EMPTY(); this.showForm = true; }
  openEdit(it: PortfolioItem): void { this.editing = it.id; this.form = { ...it }; this.showForm = true; }
  closeForm(): void { this.showForm = false; }

  // Preview en vivo
  get fTotal(): number { return (+(this.form.purchase_price || 0)) * (+(this.form.quantity || 1)); }
  get fProfit(): number { return ((+(this.form.suggested_sale_price || 0)) - (+(this.form.purchase_price || 0))) * (+(this.form.quantity || 1)); }
  get fRoi(): number {
    const c = +(this.form.purchase_price || 0);
    return c > 0 ? Math.round(((+(this.form.suggested_sale_price || 0)) - c) / c * 1000) / 10 : 0;
  }

  save(): void {
    if (!(this.form.product_name || '').trim()) { this.showToast('El nombre del producto es obligatorio'); return; }
    this.saving = true;
    const req = this.editing
      ? this.http.put<any>(`${this.base}/${this.editing}`, this.form)
      : this.http.post<any>(this.base, this.form);
    req.pipe(finalize(() => this.saving = false)).subscribe({
      next: () => { this.showForm = false; this.showToast(this.editing ? 'Producto actualizado' : 'Agregado al portafolio'); this.load(); },
      error: e => { this.showToast(e?.error?.detail || 'Error al guardar'); },
    });
  }

  markSold(it: PortfolioItem): void {
    this.editing = it.id;
    this.form = { ...it, status: 'Vendido', final_sale_price: it.final_sale_price || it.suggested_sale_price };
    this.showForm = true;
  }
  cancelItem(it: PortfolioItem): void {
    this.http.put<any>(`${this.base}/${it.id}`, { status: 'Cancelado' }).subscribe({
      next: () => { this.showToast('Producto cancelado'); this.load(); },
      error: () => this.showToast('Error al cancelar'),
    });
  }
  remove(it: PortfolioItem): void {
    if (!confirm(`¿Eliminar "${it.product_name}" del portafolio?`)) return;
    this.http.delete(`${this.base}/${it.id}`).subscribe({
      next: () => { this.showToast('Eliminado'); this.load(); },
      error: () => this.showToast('Error al eliminar'),
    });
  }
  verDetalle(it: PortfolioItem): void { this.detail = it; }
  closeDetail(): void { this.detail = null; }

  private showToast(msg: string): void {
    this.toast = msg;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast = '', 2600);
  }

  statusClass(s: string): string {
    const m: Record<string, string> = {
      'Comprado': 'st-comprado', 'En tránsito': 'st-transito', 'Recibido': 'st-recibido',
      'Publicado': 'st-publicado', 'Vendido': 'st-vendido', 'Cancelado': 'st-cancelado',
    };
    return m[s] ?? 'st-comprado';
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
  money(v: number): string { return `S/ ${(v ?? 0).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
}
