import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface TplConfig {
  logo: string; colorPrincipal: string; colorSecundario: string; tipografia: string;
  posiciones: Record<string, string>;
  elementos: Record<string, boolean>;
}
interface Template {
  id: string; nombre: string; canal: string; categoria: string; tipo: string;
  resolucion: string; config_json: TplConfig; estado: string; usos: number;
  created_at: string; updated_at: string;
}
interface Kpis {
  totalPlantillas: number; plantillasActivas: number; plantillasBorrador: number;
  plantillaMasUsada: string; plantillaMasUsadaUsos: number; ultimaModificacion: string;
}

const RESOLUCION: Record<string, string> = {
  Telegram: '1080x1080', Facebook: '1200x630', Instagram: '1080x1350',
  TikTok: '1080x1920', 'YouTube Shorts': '1080x1920', WhatsApp: '1080x1080',
};

function defaultConfig(color = '#00E58F'): TplConfig {
  return {
    logo: '', colorPrincipal: color, colorSecundario: '#0d1117', tipografia: 'Inter',
    posiciones: {
      producto: 'center', precio: 'bottom-left', descuento: 'top-right', scoreIA: 'top-left',
      botonComprar: 'bottom-center', qr: 'bottom-right', tienda: 'top-center', marca: 'bottom-left',
    },
    elementos: {
      logo: true, precioAnterior: true, precioActual: true, descuento: true, scoreIA: true,
      marca: true, categoria: false, tienda: true, qr: false, cta: true, hashtags: true, fecha: false,
    },
  };
}

@Component({
  selector: 'app-plantillas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './plantillas.component.html',
  styleUrls: ['./plantillas.component.css'],
})
export class PlantillasComponent implements OnInit {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/templates';

  loading = false;
  items: Template[] = [];
  kpis: Kpis | null = null;
  channels: string[] = [];
  categories: string[] = [];
  estados: string[] = ['Activa', 'Borrador'];

  fCanal = '';
  fCategoria = '';
  fEstado = '';

  // Editor
  showEditor = false;
  editing: string | null = null;
  form: Partial<Template> = {};
  saving = false;

  // Preview / vista previa
  showPreview = false;
  previewTpl: Template | null = null;
  previewDevice: 'desktop' | 'tablet' | 'mobile' = 'mobile';
  previewChannel = '';

  toast = '';
  private toastTimer: any = null;

  readonly tipografias = ['Inter', 'Poppins', 'Montserrat', 'Roboto', 'Oswald', 'Bebas Neue'];
  readonly zonas = [
    { v: 'top-left', l: '↖' }, { v: 'top-center', l: '↑' }, { v: 'top-right', l: '↗' },
    { v: 'center-left', l: '←' }, { v: 'center', l: '•' }, { v: 'center-right', l: '→' },
    { v: 'bottom-left', l: '↙' }, { v: 'bottom-center', l: '↓' }, { v: 'bottom-right', l: '↘' },
  ];
  readonly posicionElementos = [
    { k: 'producto', l: 'Producto' }, { k: 'precio', l: 'Precio' }, { k: 'descuento', l: 'Descuento' },
    { k: 'scoreIA', l: 'Score IA' }, { k: 'botonComprar', l: 'Botón Comprar' }, { k: 'qr', l: 'QR' },
    { k: 'tienda', l: 'Tienda' }, { k: 'marca', l: 'Marca' },
  ];
  readonly elementos = [
    { k: 'logo', l: 'Logo' }, { k: 'precioAnterior', l: 'Precio anterior' }, { k: 'precioActual', l: 'Precio actual' },
    { k: 'descuento', l: 'Descuento' }, { k: 'scoreIA', l: 'Score IA' }, { k: 'marca', l: 'Marca' },
    { k: 'categoria', l: 'Categoría' }, { k: 'tienda', l: 'Tienda' }, { k: 'qr', l: 'Código QR' },
    { k: 'cta', l: 'CTA' }, { k: 'hashtags', l: 'Hashtags' }, { k: 'fecha', l: 'Fecha' },
  ];

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    const params: Record<string, string> = {};
    if (this.fCanal) params['canal'] = this.fCanal;
    if (this.fCategoria) params['categoria'] = this.fCategoria;
    if (this.fEstado) params['estado'] = this.fEstado;
    this.http.get<any>(this.base, { params }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.items = r.items ?? [];
        this.channels = r.channels ?? [];
        this.categories = r.categories ?? [];
        this.estados = r.estados ?? this.estados;
      },
      error: () => { this.items = []; },
    });
    this.http.get<any>(`${this.base}/summary`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} });
  }
  onFilter(): void { this.load(); }
  clearFilters(): void { this.fCanal = ''; this.fCategoria = ''; this.fEstado = ''; this.load(); }

  // ── Editor ──
  openNew(): void {
    this.editing = null;
    this.form = {
      nombre: '', canal: 'Telegram', categoria: 'Flash Sale', tipo: 'post',
      resolucion: RESOLUCION['Telegram'], estado: 'Borrador', config_json: defaultConfig(),
    };
    this.previewChannel = 'Telegram';
    this.showEditor = true;
  }
  openEdit(t: Template): void {
    this.editing = t.id;
    this.form = { ...t, config_json: JSON.parse(JSON.stringify(t.config_json ?? defaultConfig())) };
    this.previewChannel = t.canal;
    this.showEditor = true;
  }
  closeEditor(): void { this.showEditor = false; }
  onCanalChange(): void {
    if (this.form.canal) { this.form.resolucion = RESOLUCION[this.form.canal] ?? '1080x1080'; this.previewChannel = this.form.canal; }
  }
  get cfg(): TplConfig { return (this.form.config_json ?? defaultConfig()) as TplConfig; }

  save(): void {
    if (!(this.form.nombre || '').trim()) { this.showToast('El nombre es obligatorio'); return; }
    this.saving = true;
    const req = this.editing
      ? this.http.put<any>(`${this.base}/${this.editing}`, this.form)
      : this.http.post<any>(this.base, this.form);
    req.pipe(finalize(() => this.saving = false)).subscribe({
      next: () => { this.showEditor = false; this.showToast(this.editing ? 'Plantilla actualizada' : 'Plantilla creada'); this.load(); },
      error: e => this.showToast(e?.error?.detail || 'Error al guardar'),
    });
  }
  duplicate(t: Template): void {
    this.http.post<any>(`${this.base}/${t.id}/duplicate`, {}).subscribe({
      next: () => { this.showToast('Plantilla duplicada'); this.load(); },
      error: () => this.showToast('Error al duplicar'),
    });
  }
  remove(t: Template): void {
    if (!confirm(`¿Eliminar la plantilla "${t.nombre}"?`)) return;
    this.http.delete(`${this.base}/${t.id}`).subscribe({
      next: () => { this.showToast('Plantilla eliminada'); this.load(); },
      error: () => this.showToast('Error al eliminar'),
    });
  }

  // ── Preview modal (desde la tarjeta) ──
  openPreview(t: Template): void { this.previewTpl = t; this.previewChannel = t.canal; this.previewDevice = 'mobile'; this.showPreview = true; }
  closePreview(): void { this.showPreview = false; this.previewTpl = null; }

  // ── Helpers de preview ──
  cfgOf(t: Template | Partial<Template> | null): TplConfig {
    return ((t?.config_json) ?? defaultConfig()) as TplConfig;
  }
  zoneStyle(zone: string): Record<string, string> {
    const z = zone || 'center';
    const s: Record<string, string> = { position: 'absolute' };
    if (z.startsWith('top')) s['top'] = '7%';
    else if (z.startsWith('bottom')) s['bottom'] = '7%';
    else { s['top'] = '50%'; s['transform'] = 'translateY(-50%)'; }
    if (z.endsWith('left')) s['left'] = '6%';
    else if (z.endsWith('right')) s['right'] = '6%';
    else {
      s['left'] = '50%';
      s['transform'] = (s['transform'] ? 'translate(-50%,-50%)' : 'translateX(-50%)');
    }
    return s;
  }
  aspectOf(channel: string): number {
    const m: Record<string, number> = {
      Telegram: 1, WhatsApp: 1, Facebook: 1.91, Instagram: 0.8, TikTok: 0.5625, 'YouTube Shorts': 0.5625,
    };
    return m[channel] ?? 1;
  }
  deviceWidth(): number { return this.previewDevice === 'desktop' ? 400 : this.previewDevice === 'tablet' ? 320 : 260; }
  previewStyle(channel: string): Record<string, string> {
    const w = this.deviceWidth();
    return { width: `${w}px`, height: `${Math.round(w / this.aspectOf(channel))}px` };
  }
  el(cfg: TplConfig, key: string): boolean { return !!cfg?.elementos?.[key]; }
  pos(cfg: TplConfig, key: string): string { return cfg?.posiciones?.[key] || 'center'; }

  private showToast(msg: string): void {
    this.toast = msg;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast = '', 2600);
  }

  canalClass(c: string): string {
    const m: Record<string, string> = {
      Telegram: 'ch-telegram', Facebook: 'ch-facebook', Instagram: 'ch-instagram',
      TikTok: 'ch-tiktok', 'YouTube Shorts': 'ch-youtube', WhatsApp: 'ch-whatsapp',
    };
    return m[c] ?? 'ch-default';
  }
}
