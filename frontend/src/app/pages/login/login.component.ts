import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.css'],
})
export class LoginComponent {
  private auth   = inject(AuthService);
  private router = inject(Router);

  username = '';
  password = '';
  loading  = false;
  error    = '';

  submit(): void {
    if (!this.username || !this.password) return;
    this.loading = true;
    this.error   = '';

    this.auth.login(this.username, this.password).subscribe(ok => {
      this.loading = false;
      if (ok) {
        this.router.navigate(['/oportunidades']);
      } else {
        this.error = 'Usuario o contraseña incorrectos';
      }
    });
  }
}
