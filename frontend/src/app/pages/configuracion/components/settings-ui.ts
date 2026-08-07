/**
 * Componentes reutilizables del Centro de Configuración.
 *
 * Van todos en un archivo porque son piezas de presentación pequeñas y sin
 * estado propio; cada una es un standalone component independiente y se puede
 * importar suelta desde cualquier vista.
 */
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

// ── Modelos compartidos ──────────────────────────────────────────────────────
export interface SettingItem {
  category: string;
  key: string;
  label: string;
  type: 'text' | 'textarea' | 'number' | 'bool' | 'select' | 'color' | 'time_range' | 'list' | 'url';
  value: any;
  default: any;
  description: string;
  options: string[];
  min: number | null;
  max: number | null;
  unit: string;
  preparado: boolean;
  is_default: boolean;
  updated_by: string | null;
  updated_at: string | null;
}

export interface CategoryMeta {
  id: string;
  label: string;
  icon: string;
  desc: string;
}

export interface Integration {
  id: string;
  nombre: string;
  tipo: string;
  color: string;
  estado: string;
  ultimaSincronizacion: string | null;
  token: string;
  tieneToken: boolean;
  expiracion: string | null;
  cuenta: string;
  gestionadoPor: string;
  endpointBase: string;
  preparado: boolean;
}

// ── 1. ToggleSwitch ──────────────────────────────────────────────────────────
@Component({
  selector: 'ph-toggle-switch',
  standalone: true,
  imports: [CommonModule],
  template: `
    <button
      type="button"
      class="ph-toggle"
      [class.on]="checked"
      [disabled]="disabled"
      [attr.aria-pressed]="checked"
      [attr.aria-label]="label"
      (click)="onToggle()">
      <span class="knob"></span>
    </button>
  `,
  styles: [`
    .ph-toggle {
      width: 42px; height: 23px; border-radius: 99px; position: relative; cursor: pointer;
      background: rgba(255,255,255,.08); border: 1px solid var(--border);
      transition: background .18s, border-color .18s; padding: 0; flex-shrink: 0;
    }
    .ph-toggle .knob {
      position: absolute; top: 2px; left: 2px; width: 17px; height: 17px; border-radius: 50%;
      background: #6b6b7e; transition: transform .18s, background .18s;
    }
    .ph-toggle.on { background: rgba(0,229,143,.22); border-color: rgba(0,229,143,.5); }
    .ph-toggle.on .knob { transform: translateX(19px); background: var(--accent); }
    .ph-toggle:disabled { opacity: .4; cursor: not-allowed; }
  `],
})
export class ToggleSwitchComponent {
  @Input() checked = false;
  @Input() disabled = false;
  @Input() label = '';
  @Output() checkedChange = new EventEmitter<boolean>();

  onToggle(): void {
    if (this.disabled) return;
    this.checked = !this.checked;
    this.checkedChange.emit(this.checked);
  }
}

// ── 2. ColorPicker ───────────────────────────────────────────────────────────
@Component({
  selector: 'ph-color-picker',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="ph-color">
      <label class="swatch" [style.background]="value">
        <input type="color" [ngModel]="value" (ngModelChange)="emit($event)" [disabled]="disabled" />
      </label>
      <input
        class="hex" type="text" spellcheck="false" maxlength="7"
        [ngModel]="value" (ngModelChange)="emit($event)" [disabled]="disabled" />
    </div>
  `,
  styles: [`
    .ph-color { display: flex; align-items: center; gap: 8px; }
    .swatch {
      width: 34px; height: 34px; border-radius: 9px; border: 1px solid var(--border);
      cursor: pointer; position: relative; overflow: hidden; flex-shrink: 0;
    }
    .swatch input { position: absolute; inset: -4px; opacity: 0; cursor: pointer; width: 150%; height: 150%; }
    .hex {
      background: #17171a; color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 8px 10px; font-size: 13px; width: 110px;
      font-family: ui-monospace, monospace; text-transform: uppercase;
    }
    .hex:focus { border-color: var(--accent); outline: none; }
    .hex:disabled { opacity: .5; }
  `],
})
export class ColorPickerComponent {
  @Input() value = '#00E58F';
  @Input() disabled = false;
  @Output() valueChange = new EventEmitter<string>();

  emit(v: string): void {
    this.value = v;
    this.valueChange.emit(v);
  }
}

// ── 3. SettingsCard: renderiza UN ajuste según su tipo ───────────────────────
@Component({
  selector: 'ph-settings-card',
  standalone: true,
  imports: [CommonModule, FormsModule, ToggleSwitchComponent, ColorPickerComponent],
  template: `
    <div class="sc" [class.dirty]="dirty" [class.prep]="item.preparado">
      <div class="sc-head">
        <div class="sc-titles">
          <span class="sc-label">
            {{ item.label }}
            <span class="sc-tag prep" *ngIf="item.preparado" title="Campo listo, integración pendiente">preparado</span>
            <span class="sc-tag dirty" *ngIf="dirty">sin guardar</span>
            <span class="sc-tag custom" *ngIf="!item.is_default && !dirty">personalizado</span>
          </span>
          <span class="sc-desc" *ngIf="item.description">{{ item.description }}</span>
        </div>

        <div class="sc-control">
          <ph-toggle-switch
            *ngIf="item.type === 'bool'"
            [checked]="!!item.value" [disabled]="item.preparado" [label]="item.label"
            (checkedChange)="change($event)" />

          <ph-color-picker
            *ngIf="item.type === 'color'"
            [value]="item.value" [disabled]="item.preparado"
            (valueChange)="change($event)" />

          <select
            *ngIf="item.type === 'select'"
            [ngModel]="item.value" (ngModelChange)="change($event)" [disabled]="item.preparado">
            <option *ngFor="let o of item.options" [value]="o">{{ o }}</option>
          </select>

          <div class="num-wrap" *ngIf="item.type === 'number'">
            <input
              type="number" [ngModel]="item.value" (ngModelChange)="change(+$event)"
              [min]="item.min" [max]="item.max" [disabled]="item.preparado" />
            <span class="unit" *ngIf="item.unit">{{ item.unit }}</span>
          </div>

          <textarea
            *ngIf="item.type === 'textarea' || item.type === 'list'"
            rows="2" [ngModel]="item.value" (ngModelChange)="change($event)" [disabled]="item.preparado"></textarea>

          <input
            *ngIf="item.type === 'text' || item.type === 'url' || item.type === 'time_range'"
            type="text" spellcheck="false"
            [ngModel]="item.value" (ngModelChange)="change($event)" [disabled]="item.preparado"
            [placeholder]="item.type === 'time_range' ? 'HH:MM-HH:MM' : ''" />
        </div>
      </div>

      <div class="sc-foot" *ngIf="item.updated_by || (item.min !== null && item.type === 'number')">
        <span class="sc-range" *ngIf="item.min !== null && item.type === 'number'">
          rango {{ item.min }}–{{ item.max }}{{ item.unit ? ' ' + item.unit : '' }}
        </span>
        <span class="sc-by" *ngIf="item.updated_by">
          modificado por {{ item.updated_by }}<span *ngIf="item.updated_at"> · {{ item.updated_at | date:'dd/MM/yyyy HH:mm' }}</span>
        </span>
      </div>
    </div>
  `,
  styles: [`
    .sc { border-bottom: 1px solid var(--border); padding: 14px 0; }
    .sc:last-child { border-bottom: none; }
    .sc.prep { opacity: .68; }
    .sc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
    .sc-titles { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
    .sc-label { font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sc-desc { font-size: 11.5px; color: var(--muted); line-height: 1.45; max-width: 560px; }
    .sc-tag { font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; letter-spacing: .3px; }
    .sc-tag.prep   { background: rgba(255,204,102,.13); color: #ffcc66; }
    .sc-tag.dirty  { background: rgba(255,159,90,.16); color: #ff9f5a; }
    .sc-tag.custom { background: rgba(0,229,143,.12); color: #00E58F; }
    .sc-control { flex-shrink: 0; min-width: 220px; display: flex; justify-content: flex-end; }
    .sc-control select, .sc-control input[type="text"], .sc-control input[type="number"], .sc-control textarea {
      background: #17171a; color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 8px 11px; font-size: 13px; width: 100%; max-width: 260px; font-family: inherit;
    }
    .sc-control select { cursor: pointer; }
    .sc-control select:focus, .sc-control input:focus, .sc-control textarea:focus { border-color: var(--accent); outline: none; }
    .sc-control select:disabled, .sc-control input:disabled, .sc-control textarea:disabled { opacity: .5; cursor: not-allowed; }
    .sc-control textarea { resize: vertical; line-height: 1.45; }
    .num-wrap { display: flex; align-items: center; gap: 7px; }
    .num-wrap input { max-width: 120px; text-align: right; }
    .unit { font-size: 11px; color: var(--muted); white-space: nowrap; }
    .sc-foot { display: flex; gap: 14px; margin-top: 7px; font-size: 10.5px; color: var(--muted); flex-wrap: wrap; }
  `],
})
export class SettingsCardComponent {
  @Input({ required: true }) item!: SettingItem;
  @Input() dirty = false;
  @Output() valueChange = new EventEmitter<any>();

  change(v: any): void {
    this.item.value = v;
    this.valueChange.emit(v);
  }
}

// ── 4. SettingsSection: cabecera + contenedor de una pestaña ─────────────────
@Component({
  selector: 'ph-settings-section',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="ss">
      <header class="ss-head">
        <div>
          <h3>{{ title }}</h3>
          <p *ngIf="subtitle">{{ subtitle }}</p>
        </div>
        <ng-content select="[actions]"></ng-content>
      </header>
      <div class="ss-body">
        <ng-content></ng-content>
      </div>
    </section>
  `,
  styles: [`
    .ss { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; animation: ssIn .22s ease; }
    @keyframes ssIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
    .ss-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 18px; border-bottom: 1px solid var(--border); background: var(--surface2); }
    .ss-head h3 { margin: 0 0 3px; font-size: 15px; }
    .ss-head p { margin: 0; font-size: 12px; color: var(--muted); }
    .ss-body { padding: 4px 18px 14px; }
  `],
})
export class SettingsSectionComponent {
  @Input() title = '';
  @Input() subtitle = '';
}

// ── 5. SettingsSidebar: menú lateral interno ─────────────────────────────────
@Component({
  selector: 'ph-settings-sidebar',
  standalone: true,
  imports: [CommonModule],
  template: `
    <nav class="ssb">
      <button
        *ngFor="let c of categories"
        type="button"
        class="ssb-item"
        [class.active]="c.id === active"
        (click)="select.emit(c.id)">
        <span class="ssb-dot"></span>
        <span class="ssb-txt">
          <span class="ssb-label">{{ c.label }}</span>
          <span class="ssb-desc">{{ c.desc }}</span>
        </span>
        <span class="ssb-count" *ngIf="dirtyByCategory[c.id]">{{ dirtyByCategory[c.id] }}</span>
      </button>
    </nav>
  `,
  styles: [`
    .ssb { display: flex; flex-direction: column; gap: 2px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 8px; position: sticky; top: 12px; }
    .ssb-item {
      display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
      background: transparent; border: none; border-radius: 9px; padding: 9px 11px;
      cursor: pointer; color: var(--muted2); transition: background .14s, color .14s;
    }
    .ssb-item:hover { background: rgba(255,255,255,.03); color: var(--text); }
    .ssb-item.active { background: rgba(0,229,143,.09); color: var(--text); }
    .ssb-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .35; flex-shrink: 0; }
    .ssb-item.active .ssb-dot { background: var(--accent); opacity: 1; box-shadow: 0 0 8px rgba(0,229,143,.6); }
    .ssb-txt { display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1; }
    .ssb-label { font-size: 13px; font-weight: 600; }
    .ssb-desc { font-size: 10.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ssb-count { font-size: 10px; font-weight: 800; background: rgba(255,159,90,.18); color: #ff9f5a; border-radius: 99px; padding: 2px 7px; flex-shrink: 0; }
    @media (max-width: 1000px) {
      .ssb { flex-direction: row; overflow-x: auto; position: static; }
      .ssb-item { flex-direction: column; align-items: flex-start; min-width: 140px; }
      .ssb-desc { display: none; }
    }
  `],
})
export class SettingsSidebarComponent {
  @Input() categories: CategoryMeta[] = [];
  @Input() active = '';
  @Input() dirtyByCategory: Record<string, number> = {};
  @Output() select = new EventEmitter<string>();
}

// ── 6. SystemStatusCard: una métrica de sistema con barra ────────────────────
@Component({
  selector: 'ph-system-status-card',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="ssc" [class.warn]="isWarn" [class.crit]="isCrit">
      <span class="ssc-label">{{ label }}</span>
      <span class="ssc-value">{{ value }}</span>
      <div class="ssc-bar" *ngIf="percent !== null">
        <span [style.width.%]="percent"></span>
      </div>
      <span class="ssc-sub" *ngIf="sub">{{ sub }}</span>
    </div>
  `,
  styles: [`
    .ssc { background: var(--surface2); border: 1px solid var(--border); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 5px; }
    .ssc-label { font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .4px; }
    .ssc-value { font-size: 20px; font-weight: 800; color: var(--accent); }
    .ssc-sub { font-size: 10.5px; color: var(--muted); }
    .ssc-bar { height: 5px; border-radius: 99px; background: rgba(255,255,255,.07); overflow: hidden; margin-top: 2px; }
    .ssc-bar span { display: block; height: 100%; background: var(--accent); border-radius: 99px; transition: width .4s ease; }
    .ssc.warn .ssc-value, .ssc.warn .ssc-bar span { color: #ffcc66; background-color: #ffcc66; }
    .ssc.warn .ssc-value { background: none; }
    .ssc.crit .ssc-value { color: #ff6b6b; }
    .ssc.crit .ssc-bar span { background: #ff6b6b; }
  `],
})
export class SystemStatusCardComponent {
  @Input() label = '';
  @Input() value = '';
  @Input() sub = '';
  @Input() percent: number | null = null;

  get isWarn(): boolean { return this.percent !== null && this.percent >= 75 && this.percent < 90; }
  get isCrit(): boolean { return this.percent !== null && this.percent >= 90; }
}

// ── 7. IntegrationCard ───────────────────────────────────────────────────────
@Component({
  selector: 'ph-integration-card',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="ic">
      <div class="ic-top">
        <span class="ic-dot" [style.background]="item.color"></span>
        <div class="ic-id">
          <b>{{ item.nombre }}</b>
          <span>{{ item.tipo }}</span>
        </div>
        <span class="ic-state" [class.on]="item.estado === 'Conectado'" [class.err]="item.estado === 'Error' || item.estado === 'Expirado'">
          {{ item.estado }}
        </span>
      </div>

      <dl class="ic-meta">
        <div><dt>Última sincronización</dt><dd>{{ item.ultimaSincronizacion ? (item.ultimaSincronizacion | date:'dd/MM/yyyy HH:mm') : '—' }}</dd></div>
        <div><dt>Token</dt><dd class="mono">{{ item.token || '—' }}</dd></div>
        <div><dt>Expiración</dt><dd>{{ item.expiracion ? (item.expiracion | date:'dd/MM/yyyy') : 'No expira' }}</dd></div>
        <div *ngIf="item.cuenta"><dt>Cuenta</dt><dd>{{ item.cuenta }}</dd></div>
      </dl>

      <div class="ic-actions">
        <button type="button" class="ib" [disabled]="busy || item.estado === 'Conectado'" (click)="action.emit('connect')">Conectar</button>
        <button type="button" class="ib" [disabled]="busy || item.estado !== 'Conectado'" (click)="action.emit('disconnect')">Desconectar</button>
        <button type="button" class="ib test" [disabled]="busy || !item.tieneToken" (click)="action.emit('test')">Probar</button>
        <button type="button" class="ib" [disabled]="busy || !item.tieneToken" (click)="action.emit('renew')">Renovar token</button>
      </div>
      <p class="ic-note" *ngIf="item.gestionadoPor === 'settings'">
        Se configura en esta misma pestaña (campos de abajo).
      </p>
      <p class="ic-note" *ngIf="item.gestionadoPor === 'channels'">
        Gestionado por el módulo Canales.
      </p>
    </div>
  `,
  styles: [`
    .ic { background: var(--surface2); border: 1px solid var(--border); border-radius: 13px; padding: 14px; display: flex; flex-direction: column; gap: 11px; transition: border-color .15s; }
    .ic:hover { border-color: rgba(255,255,255,.14); }
    .ic-top { display: flex; align-items: center; gap: 10px; }
    .ic-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
    .ic-id { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
    .ic-id b { font-size: 13.5px; }
    .ic-id span { font-size: 10.5px; color: var(--muted); }
    .ic-state { font-size: 10px; font-weight: 700; padding: 3px 9px; border-radius: 99px; text-transform: uppercase; letter-spacing: .3px; background: rgba(255,255,255,.05); color: #8a8a9e; white-space: nowrap; }
    .ic-state.on  { background: rgba(0,229,143,.13); color: #00E58F; }
    .ic-state.err { background: rgba(255,107,107,.13); color: #ff6b6b; }
    .ic-meta { margin: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .ic-meta > div { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .ic-meta dt { font-size: 10px; color: var(--muted); }
    .ic-meta dd { margin: 0; font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ic-meta dd.mono { font-family: ui-monospace, monospace; font-size: 11px; }
    .ic-actions { display: flex; gap: 6px; flex-wrap: wrap; }
    .ib { flex: 1 1 auto; padding: 7px 9px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--text); font-size: 11px; font-weight: 600; cursor: pointer; }
    .ib:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
    .ib.test:hover:not(:disabled) { border-color: #6ab0ff; color: #6ab0ff; }
    .ib:disabled { opacity: .35; cursor: not-allowed; }
    .ic-note { margin: 0; font-size: 10.5px; color: var(--muted); }
  `],
})
export class IntegrationCardComponent {
  @Input({ required: true }) item!: Integration;
  @Input() busy = false;
  @Output() action = new EventEmitter<'connect' | 'disconnect' | 'test' | 'renew'>();
}

// ── 8. ConfigurationTable: bitácora de cambios ───────────────────────────────
@Component({
  selector: 'ph-configuration-table',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="ct-wrap">
      <table class="ct">
        <thead>
          <tr>
            <th>Ajuste</th>
            <th>Categoría</th>
            <th>Valor anterior</th>
            <th>Valor nuevo</th>
            <th>Usuario</th>
            <th>Fecha</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let r of rows">
            <td><b>{{ r.label }}</b></td>
            <td class="mut">{{ r.category }}</td>
            <td><span class="old">{{ r.old_value || '—' }}</span></td>
            <td><span class="new">{{ r.new_value || '—' }}</span></td>
            <td class="mut">{{ r.updated_by || '—' }}</td>
            <td class="mut">{{ r.created_at ? (r.created_at | date:'dd/MM/yyyy HH:mm') : '—' }}</td>
          </tr>
          <tr *ngIf="!rows.length">
            <td colspan="6" class="empty">Todavía no hay cambios registrados.</td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  styles: [`
    .ct-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; }
    .ct { width: 100%; border-collapse: collapse; font-size: 12.5px; min-width: 760px; }
    .ct thead th { text-align: left; padding: 10px 12px; font-size: 10.5px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .4px; background: var(--surface2); border-bottom: 1px solid var(--border); white-space: nowrap; }
    .ct tbody tr { border-bottom: 1px solid var(--border); }
    .ct tbody tr:last-child { border-bottom: none; }
    .ct td { padding: 9px 12px; vertical-align: middle; }
    .ct td.mut { color: var(--muted2); }
    .ct td.empty { text-align: center; color: var(--muted); padding: 26px; }
    .old { color: #ff6b6b; text-decoration: line-through; font-family: ui-monospace, monospace; font-size: 11.5px; }
    .new { color: var(--accent); font-family: ui-monospace, monospace; font-size: 11.5px; }
  `],
})
export class ConfigurationTableComponent {
  @Input() rows: {
    label: string; category: string; key: string;
    old_value: string; new_value: string; updated_by: string; created_at: string;
  }[] = [];
}
