import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DealsStateService } from '../../services/deals-state.service';

@Component({
  selector: 'app-alertas',
  templateUrl: './alertas.component.html',
  standalone: true,
  imports: [CommonModule],
})
export class AlertasComponent {
  protected s = inject(DealsStateService);
}
