import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DealsStateService } from '../../services/deals-state.service';

@Component({
  selector: 'app-gangas',
  templateUrl: './gangas.component.html',
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class GangasComponent {
  protected s = inject(DealsStateService);
}
