import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface Store {
  id: string; nombre: string; logo: string; dominio: string; tipo: string; scraper_asociado: string;
  estado: string; color: string; categoria: string; url: string; frecuencia: string;
  productos: number; ultimoScraping: string | null; tiempoPromedio: number; errores: number;
  ultimaSincronizacion: string | null; scraperEstado: string; created_at: string; updated_at: string;
}
interface Kpis { totalTiendas: number; activas: number; inactivas: number; productosTotales: number; conError: number; }
interface Hist { fecha: string; duracion: number | null; productos: number; errores: number; estado: string; }

@Component({
  selector: 'app-tiendas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './tiendas.component.html',
  styleUrls: ['./tiendas.component.css'],
})
export class TiendasComponent implements OnInit {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/stores';

  loading = false;
  items: Store[] = [];
  kpis: Kpis | null = null;
  tipos: string[] = []; categorias: string[] = []; frecuencias: string[] = [];

  showForm = false;
  editing: string | null = null;
  form: Partial<Store> = {};
  saving = false;

  historyStore: Store | null = null;
  history: Hist[] = [];

  toast = '';
  private toastTimer: any = null;

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    this.http.get<any>(this.base).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.items ?? []; this.tipos = r.tipos ?? []; this.categorias = r.categorias ?? []; this.frecuencias = r.frecuencias ?? []; },
      error: () => { this.items = []; },
    });
    this.http.get<any>(`${this.base}/stats`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} });
  }

  openNew(): void { this.editing = null; this.form = { nombre: '', dominio: '', tipo: 'Requests', categoria: 'Retail', color: '#00E58F', frecuencia: 'Manual', estado: 'Inactivo', url: '' }; this.showForm = true; }
  openEdit(s: Store): void { this.editing = s.id; this.form = { ...s }; this.showForm = true; }
  closeForm(): void { this.showForm = false; }

  save(): void {
    if (!(this.form.nombre || '').trim()) { this.showToast('El nombre es obligatorio'); return; }
    this.saving = true;
    const req = this.editing ? this.http.put<any>(`${this.base}/${this.editing}`, this.form) : this.http.post<any>(this.base, this.form);
    req.pipe(finalize(() => this.saving = false)).subscribe({
      next: () => { this.showForm = false; this.showToast(this.editing ? 'Tienda actualizada' : 'Tienda creada'); this.load(); },
      error: e => this.showToast(e?.error?.detail || 'Error al guardar'),
    });
  }
  toggle(s: Store): void {
    this.http.post<any>(`${this.base}/${s.id}/toggle`, {}).subscribe({
      next: r => { this.showToast(`${s.nombre} ${r.item.estado === 'Activo' ? 'activada' : 'desactivada'}`); this.load(); },
      error: () => this.showToast('Error'),
    });
  }
  test(s: Store): void {
    this.showToast(`Probando scraper de ${s.nombre}…`);
    this.http.post<any>(`${this.base}/${s.id}/test`, {}).subscribe({
      next: () => { this.showToast(`Scraper de ${s.nombre} en ejecución`); setTimeout(() => this.load(), 1500); },
      error: e => this.showToast(e?.error?.detail || 'No se pudo probar'),
    });
  }
  remove(s: Store): void {
    if (!confirm(`¿Eliminar la tienda ${s.nombre}?`)) return;
    this.http.delete(`${this.base}/${s.id}`).subscribe({ next: () => { this.showToast('Tienda eliminada'); this.load(); }, error: () => this.showToast('Error') });
  }
  openHistory(s: Store): void {
    this.historyStore = s; this.history = [];
    this.http.get<any>(`${this.base}/${s.id}/history`).subscribe({ next: r => this.history = r.items ?? [], error: () => this.history = [] });
  }
  closeHistory(): void { this.historyStore = null; }

  private showToast(msg: string): void { this.toast = msg; clearTimeout(this.toastTimer); this.toastTimer = setTimeout(() => this.toast = '', 2600); }
  scStatusClass(s: string): string {
    const m: Record<string, string> = { Activo: 'sc-ok', Ejecutando: 'sc-run', Pausado: 'sc-pause', Error: 'sc-err', Deshabilitado: 'sc-dis' };
    return m[s] ?? 'sc-dis';
  }
}
