import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DealsStateService } from '../../services/deals-state.service';

@Component({
  selector: 'app-oportunidades',
  templateUrl: './oportunidades.component.html',
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class OportunidadesComponent {
  protected s = inject(DealsStateService);

  buyPrice = 0;
  sellPrice = 0;
  additionalCosts = 0;

  get profit():    number { return this.sellPrice - this.buyPrice - this.additionalCosts; }
  get margin():    number { return this.sellPrice ? (this.profit / this.sellPrice) * 100 : 0; }
  get roi():       number { return this.buyPrice  ? (this.profit / this.buyPrice) * 100 : 0; }
  get breakEven(): number { return this.buyPrice + this.additionalCosts; }

  get marginClass(): string {
    return this.margin >= 25 ? 'good' : this.margin >= 10 ? 'warn' : 'bad';
  }
  get marginStatus(): string {
    if (this.margin >= 25) return 'Margen saludable: conviene evaluar la oportunidad.';
    if (this.margin >= 10) return 'Margen moderado: revisar costos y precio de venta.';
    return 'Margen bajo: probablemente no compense.';
  }
}
