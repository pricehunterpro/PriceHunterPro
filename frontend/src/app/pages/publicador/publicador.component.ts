import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface PubItem {
  id: string;
  titulo: string;
  store: string;
  category: string;
  currentPrice: number;
  originalPrice: number;
  discountPct: number;
  imageUrl: string;
  url: string;
  canalesSeleccionados: string[];
  contenido: string;
  hashtags: string[];
  scoreIA: number;
  estado: string;
  fechaProgramada: string | null;
  fechaPublicacion: string | null;
  generadoAt: string | null;
}

interface Kpis {
  total: number;
  pendientes: number;
  generados: number;
  aprobados: number;
  programados: number;
  publicados: number;
  errores: number;
}

const ALL_CANALES = ['Telegram', 'Facebook', 'Instagram', 'TikTok'];

@Component({
  selector: 'app-publicador',
  templateUrl: './publicador.component.html',
  styleUrls: ['./publicador.component.css'],
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class PublicadorComponent implements OnInit {
  private http = inject(HttpClient);

  items: PubItem[] = [];
  kpis: Kpis | null = null;
  allCanales: string[] = ALL_CANALES;
  estados: string[] = [];
  loading = false;

  filtroEstado = '';
  filtroCanal = '';

  // estado inline por tarjeta
  editId = '';
  editContenido = '';
  editHashtags = '';
  editCanales: string[] = [];

  programarId = '';
  programarFecha = '';

  generando: Set<string> = new Set();

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    const params: Record<string, string> = {};
    if (this.filtroEstado) params['estado'] = this.filtroEstado;
    if (this.filtroCanal) params['canal'] = this.filtroCanal;
    this.http.get<{ items: PubItem[]; kpis: Kpis; canales: string[]; estados: string[] }>(
      '/api/v1/publicador/items', { params }
    ).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.items = r.items ?? [];
        this.kpis = r.kpis;
        this.estados = r.estados ?? [];
      },
      error: () => { this.items = []; },
    });
  }

  generar(it: PubItem): void {
    this.generando.add(it.id);
    this.http.post('/api/v1/publicador/generar', { id: it.id })
      .pipe(finalize(() => this.generando.delete(it.id)))
      .subscribe({ next: () => this.load(), error: (e) => alert(e?.error?.detail || 'Error al generar') });
  }

  aprobar(it: PubItem): void {
    this.http.post('/api/v1/publicador/aprobar', { id: it.id })
      .subscribe({ next: () => this.load(), error: (e) => alert(e?.error?.detail || 'Error al aprobar') });
  }

  publicar(it: PubItem): void {
    this.http.post('/api/v1/publicador/publicar', { id: it.id }).subscribe({
      next: () => this.load(),
      error: (e) => alert(e?.error?.detail || 'No se pudo publicar'),
    });
  }

  openProgramar(it: PubItem): void {
    this.cancelInline();
    this.programarId = it.id;
    this.programarFecha = '';
  }

  confirmProgramar(): void {
    if (!this.programarFecha) return;
    this.http.post('/api/v1/publicador/programar', { id: this.programarId, fecha: this.programarFecha })
      .subscribe({ next: () => { this.programarId = ''; this.load(); }, error: (e) => alert(e?.error?.detail || 'Error') });
  }

  openEdit(it: PubItem): void {
    this.cancelInline();
    this.editId = it.id;
    this.editContenido = it.contenido;
    this.editHashtags = (it.hashtags || []).join(' ');
    this.editCanales = [...(it.canalesSeleccionados || [])];
  }

  toggleEditCanal(canal: string): void {
    const idx = this.editCanales.indexOf(canal);
    if (idx >= 0) {
      if (this.editCanales.length > 1) this.editCanales.splice(idx, 1);
    } else {
      this.editCanales.push(canal);
    }
  }

  confirmEdit(): void {
    const hashtags = this.editHashtags.split(/\s+/).filter(h => h.startsWith('#'));
    this.http.post('/api/v1/publicador/update', {
      id: this.editId,
      contenido: this.editContenido,
      hashtags,
      canalesSeleccionados: this.editCanales,
    }).subscribe({ next: () => { this.editId = ''; this.load(); } });
  }

  reload(): void {
    this.http.post('/api/v1/publicador/reload', {}).subscribe({ next: () => this.load() });
  }

  cancelInline(): void {
    this.editId = '';
    this.programarId = '';
  }

  isGenerando(id: string): boolean { return this.generando.has(id); }

  estadoClass(estado: string): string {
    const map: Record<string, string> = {
      'Pendiente': 'st-pendiente', 'Generado': 'st-generado',
      'Aprobado': 'st-aprobado', 'Programado': 'st-programado',
      'Publicado': 'st-publicado', 'Error': 'st-error',
    };
    return map[estado] || 'st-pendiente';
  }

  canalClass(canal: string): string { return 'ch-' + canal.toLowerCase(); }

  scoreClass(s: number): string { return s >= 85 ? 'sc-high' : s >= 70 ? 'sc-mid' : 'sc-low'; }
}
