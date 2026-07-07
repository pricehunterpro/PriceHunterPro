import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface SupItem {
  id: string;
  titulo: string;
  store: string;
  category: string;
  currentPrice: number;
  originalPrice: number;
  discountPct: number;
  imageUrl: string;
  url: string;
  canal: string;
  contenido: string;
  scoreIA: number;
  estado: string;
  fechaProgramada: string | null;
  fechaPublicacion: string | null;
  motivoRechazo: string | null;
}

interface Kpis {
  total: number; pendientes: number; enRevision: number; aprobados: number;
  programados: number; publicados: number; rechazados: number; errores: number;
}

@Component({
  selector: 'app-supervision',
  templateUrl: './supervision.component.html',
  styleUrls: ['./supervision.component.css'],
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class SupervisionComponent implements OnInit {
  private http = inject(HttpClient);

  items: SupItem[] = [];
  kpis: Kpis | null = null;
  canales: string[] = [];
  estados: string[] = [];
  loading = false;

  filtroEstado = '';
  filtroCanal = '';

  // estado inline por tarjeta
  editId = '';
  editContenido = '';
  scheduleId = '';
  scheduleFecha = '';
  rejectId = '';
  rejectMotivo = '';

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    const params: Record<string, string> = {};
    if (this.filtroEstado) params['estado'] = this.filtroEstado;
    if (this.filtroCanal) params['canal'] = this.filtroCanal;
    this.http.get<{ items: SupItem[]; kpis: Kpis; canales: string[]; estados: string[] }>(
      '/api/v1/supervision/items', { params }
    ).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.items = r.items ?? [];
        this.kpis = r.kpis;
        this.canales = r.canales ?? [];
        this.estados = r.estados ?? [];
      },
      error: () => { this.items = []; },
    });
  }

  approve(it: SupItem): void {
    this.http.post('/api/v1/supervision/approve', { id: it.id }).subscribe(() => this.load());
  }

  publish(it: SupItem): void {
    this.http.post('/api/v1/supervision/publish', { id: it.id }).subscribe({
      next: () => this.load(),
      error: (e) => alert(e?.error?.detail || 'No se pudo publicar'),
    });
  }

  // Rechazar
  openReject(it: SupItem): void { this.rejectId = it.id; this.rejectMotivo = ''; }
  confirmReject(): void {
    this.http.post('/api/v1/supervision/reject', { id: this.rejectId, motivo: this.rejectMotivo })
      .subscribe(() => { this.rejectId = ''; this.load(); });
  }

  // Programar
  openSchedule(it: SupItem): void { this.scheduleId = it.id; this.scheduleFecha = ''; }
  confirmSchedule(): void {
    if (!this.scheduleFecha) return;
    this.http.post('/api/v1/supervision/schedule', { id: this.scheduleId, fecha: this.scheduleFecha })
      .subscribe(() => { this.scheduleId = ''; this.load(); });
  }

  // Editar
  openEdit(it: SupItem): void { this.editId = it.id; this.editContenido = it.contenido; }
  confirmEdit(): void {
    this.http.post('/api/v1/supervision/update', { id: this.editId, contenido: this.editContenido })
      .subscribe(() => { this.editId = ''; this.load(); });
  }

  cancelInline(): void { this.editId = ''; this.scheduleId = ''; this.rejectId = ''; }

  estadoClass(estado: string): string {
    const map: Record<string, string> = {
      'Pendiente': 'st-pendiente', 'Generado': 'st-generado', 'En revisión': 'st-revision',
      'Aprobado': 'st-aprobado', 'Programado': 'st-programado', 'Publicado': 'st-publicado',
      'Rechazado': 'st-rechazado', 'Error': 'st-error',
    };
    return map[estado] || 'st-pendiente';
  }
  canalClass(canal: string): string { return 'ch-' + canal.toLowerCase(); }
  scoreClass(s: number): string { return s >= 85 ? 'sc-high' : s >= 70 ? 'sc-mid' : 'sc-low'; }
}
