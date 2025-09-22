"use client";

import { cn } from "@/lib/utils";
import { ComponentProps } from "react";

interface ThinkingAnimationProps extends ComponentProps<"div"> {
  variant?: "dots" | "pulse" | "wave";
  size?: "sm" | "md" | "lg";
}

export function ThinkingAnimation({
  variant = "dots",
  size = "md",
  className,
  ...props
}: ThinkingAnimationProps) {
  const sizeClasses = {
    sm: "text-sm",
    md: "text-base",
    lg: "text-lg"
  };

  if (variant === "dots") {
    return (
      <div
        className={cn(
          "flex items-center space-x-1",
          sizeClasses[size],
          className
        )}
        {...props}
      >
        <div className="flex space-x-1">
          <div className="w-1 h-1 bg-current rounded-full animate-bounce [animation-delay:-0.3s]"></div>
          <div className="w-1 h-1 bg-current rounded-full animate-bounce [animation-delay:-0.15s]"></div>
          <div className="w-1 h-1 bg-current rounded-full animate-bounce"></div>
        </div>
      </div>
    );
  }

  if (variant === "pulse") {
    return (
      <div
        className={cn(
          "flex items-center space-x-2 text-muted-foreground",
          sizeClasses[size],
          className
        )}
        {...props}
      >
        <div className="w-2 h-2 bg-current rounded-full animate-pulse"></div>
        <span>Agent thinking...</span>
      </div>
    );
  }

  if (variant === "wave") {
    return (
      <div
        className={cn(
          "flex items-center space-x-2 text-muted-foreground",
          sizeClasses[size],
          className
        )}
        {...props}
      >
        <div className="flex space-x-1">
          <div className="w-1 h-4 bg-current rounded-full animate-pulse [animation-delay:0s] [animation-duration:1.4s]"></div>
          <div className="w-1 h-4 bg-current rounded-full animate-pulse [animation-delay:0.2s] [animation-duration:1.4s]"></div>
          <div className="w-1 h-4 bg-current rounded-full animate-pulse [animation-delay:0.4s] [animation-duration:1.4s]"></div>
        </div>
        <span>Agent thinking...</span>
      </div>
    );
  }

  return null;
}
