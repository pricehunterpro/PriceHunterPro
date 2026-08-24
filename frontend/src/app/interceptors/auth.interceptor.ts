import { inject } from '@angular/core';
import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth  = inject(AuthService);
  const token = auth.getToken();
  if (token) {
    req = req.clone({ headers: req.headers.set('Authorization', `Bearer ${token}`) });
  }
  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      // El backend ya rechaza las escrituras sin token valido: si contesta 401
      // el token esta caducado o manipulado, no tiene sentido conservarlo.
      if (err.status === 401 && !req.url.includes('/auth/')) auth.logout();
      return throwError(() => err);
    }),
  );
};
